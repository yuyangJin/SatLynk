"""
Case 1: GRB 三角定位 — 多星同时触发的带宽争抢
================================================================
3颗天格探测星同时触发 GRB，各自产出 5MB 事件包，需上传到计算星做
联合定位。瓶颈是天格星侧的 2 Mbps S-band ISL。

关键对比：
- Nearest-First: 3个任务选同一颗最近计算星 → 带宽3等分 → makespan 3×
- Bandwidth-Aware (TEG): 分散到3颗不同计算星 → 并行上传 → makespan 1×
- Static Baseline: 假设链路永远在、无争抢 → 乐观偏差
"""

import sys
import numpy as np

from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import (
    Satellite, Role, OrbitalElements, generate_walker_delta,
)
from satlynk.task.dag import TaskDAG, SubTask
from satlynk.scheduler.interface import NearestFirstScheduler
from satlynk.scheduler.heuristics import ShortestPathScheduler, CGR_EDF_Scheduler
from satlynk.scheduler.teg_scheduler import TEGScheduler


def create_constellation():
    """
    天格探测星 + 计算星座。
    关键: 通过轨道设计使 3 颗探测星在某时刻都能看到同一批计算星，
    但也能看到不同的计算星——让调度器有选择空间。
    """
    # 天格探测星: 3颗, 535km SSO, 同一轨道面间隔120°
    det_sats = []
    for i in range(3):
        det_sats.append(Satellite(
            id=f"TG-{i+1:02d}",
            role=Role.DETECTOR,
            elements=OrbitalElements(
                semi_major_axis_km=6906.0,
                inclination_deg=97.4,
                raan_deg=0.0,  # 同一面
                true_anomaly_deg=i * 120.0,
            ),
            compute_flops=0,
            storage_bytes=int(4e9),
            max_comm_range_km=3000.0,
            power_solar_w=12.0,
            battery_capacity_wh=40.0,
        ))

    # 计算星: 12颗, 550km, 53° Walker(12/3/1)
    comp_sats = generate_walker_delta(
        total_sats=12, num_planes=3, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE, prefix="COMP",
        compute_flops=1e12,
        storage_bytes=int(64e9),
        max_comm_range_km=5000.0,
        power_solar_w=80.0,
        battery_capacity_wh=300.0,
    )

    return det_sats, comp_sats


def create_burst_tasks(arrival_time=50.0, spread_s=5.0):
    """
    3 颗探测星在同一窗口内(±5s)同时触发 GRB 事件。
    每星产出 5 MB 事件包。
    """
    tasks = []
    for i in range(3):
        task = TaskDAG(
            id=f"grb_trig_{i:03d}",
            source_node=i,  # TG-01, TG-02, TG-03
            arrival_time_s=arrival_time + i * (spread_s / 3),
            subtasks=[SubTask(
                id=f"grb_localize_{i}",
                compute_flops=2e9,           # 4s on 1 TFLOPS (按模型大小)
                output_size_bytes=200_000,   # 200 KB result (天区概率图)
            )],
            dependencies=[],
            global_deadline_s=120.0,         # 2 min deadline
            result_destination=i,            # 回传触发星
            result_size_bytes=200_000,
        )
        task.input_size_bytes = 5_000_000  # 5 MB
        tasks.append(task)
    return tasks


def run_case1():
    """Run Case 1 with multiple schedulers and compare."""
    print("=" * 70)
    print("  Case 1: GRB Triangulation — Bandwidth Contention")
    print("=" * 70)

    det_sats, comp_sats = create_constellation()
    all_sats = det_sats + comp_sats
    print(f"\n  Constellation: {len(det_sats)} det + {len(comp_sats)} comp = {len(all_sats)} total")
    print(f"  Det data rate: 2 Mbps (S-band bottleneck)")
    print(f"  Comp data rate: 50 Mbps (laser ISL)")
    print(f"  3 tasks arrive within 5s window, each 5 MB input")

    config = SimConfig(
        duration_s=600.0,
        dt=1.0,
        data_rate_bps=2e6,    # Bottleneck: det S-band
        compute_flops_default=1e12,
    )

    # Precompute for TEG
    sim_pre = Simulator(config)
    sim_pre.set_satellites(all_sats)
    sim_pre.precompute_orbits()
    contact_plan = sim_pre.contact_plan
    
    print(f"  Contact windows: {len(contact_plan.windows)}")

    # Build schedulers
    schedulers = {
        "Nearest-First": NearestFirstScheduler(),
        "Shortest-Path": ShortestPathScheduler(),
        "CGR+EDF": CGR_EDF_Scheduler(),
        "TEG": TEGScheduler(
            contact_plan=contact_plan,
            satellites=all_sats,
            data_rate_bps=config.data_rate_bps,
            time_horizon_s=config.duration_s,
            teg_dt_s=10.0,
        ),
    }

    results = {}
    for name, scheduler in schedulers.items():
        sim = Simulator(config)
        sim.set_satellites(all_sats)
        sim.precompute_orbits()
        sim.set_scheduler(scheduler)

        tasks = create_burst_tasks(arrival_time=50.0, spread_s=5.0)
        for t in tasks:
            sim.add_task(t)

        metrics = sim.run()
        results[name] = metrics

        print(f"\n  {name:15s}: success={metrics.success_rate*100:.0f}% "
              f"({metrics.completed_tasks}/{metrics.total_tasks}), "
              f"avg_makespan={metrics.avg_makespan_s:.1f}s, "
              f"max_makespan={metrics.max_makespan_s:.1f}s")

    # Static baseline
    print(f"\n{'─' * 70}")
    static_makespan = 5e6 * 8 / 2e6 + 2.0 + 0.2e6 * 8 / 2e6  # 20s + 2s + 0.8s
    print(f"  Static Topology Baseline (assumes parallel, no contention):")
    print(f"    Predicted makespan: 5MB/2Mbps + 2s + 0.2MB/2Mbps = ~{static_makespan:.1f}s")
    print(f"    Predicted success:  100%")
    print(f"{'─' * 70}")

    # Analysis: bandwidth contention
    print(f"\n  Bandwidth Contention Analysis:")
    nf = results.get("Nearest-First")
    sp = results.get("Shortest-Path")
    if nf and sp:
        if nf.max_makespan_s > 0 and sp.max_makespan_s > 0:
            ratio = nf.max_makespan_s / sp.max_makespan_s if sp.max_makespan_s > 0 else 0
            print(f"    Nearest-First max makespan: {nf.max_makespan_s:.1f}s")
            print(f"    Shortest-Path max makespan: {sp.max_makespan_s:.1f}s")
            print(f"    Contention penalty: {ratio:.2f}×")

    print(f"\n{'=' * 70}")
    return results


if __name__ == "__main__":
    run_case1()
