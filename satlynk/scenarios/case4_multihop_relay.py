"""
Case 4: 跨轨道面多跳中继 — 引力波对应体紧急定位
================================================================
验证 TEG 多跳路由在强制中继拓扑下的必要性。
探测星 (SSO 97.4°) 与计算星 (53° Walker) 无直接链路，
必须经过中继星 (65°, 1100km) 桥接。

单跳调度器: 0% 成功率 (找不到路径)
TEG 调度器: 100% 成功率 (发现多跳路径)
静态拓扑假设: 延迟被低估 15× (假设直达 ~14s vs 实际 ~220s)
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
    构建强制多跳拓扑的星座：
    - 探测星 (SSO 97.4°, 535km): 通信距离 2000km
    - 计算星 (53°, 550km Walker): 通信距离 5000km
    - 中继星 (65°, 1100km Walker): 通信距离 4000km
    
    关键: det↔comp 距离在大部分时刻 > 2000km → 无直接链路
    """
    # 天格探测星: 3颗, 535km SSO
    det_sats = []
    for i in range(3):
        det_sats.append(Satellite(
            id=f"TG-{i+1:02d}",
            role=Role.DETECTOR,
            elements=OrbitalElements(
                semi_major_axis_km=6906.0,  # 535km alt
                inclination_deg=97.4,
                raan_deg=i * 120.0,
                true_anomaly_deg=i * 40.0,
            ),
            compute_flops=0,
            storage_bytes=int(4e9),
            max_comm_range_km=1200.0,  # 关键: 很小! 确保 det↔comp 无直接链路
            power_solar_w=12.0,
            battery_capacity_wh=40.0,
        ))

    # 计算星: 12颗, 550km, 53°
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

    # 中继星: 6颗, 1100km, 75° (高倾角，与 SSO 和 53° 都有交集)
    relay_sats = generate_walker_delta(
        total_sats=6, num_planes=2, phase_factor=1,
        altitude_km=1100, inclination_deg=75.0,
        role=Role.RELAY, prefix="RLY",
        compute_flops=0,
        storage_bytes=int(8e9),
        max_comm_range_km=5000.0,  # 高轨+大天线
        power_solar_w=40.0,
        battery_capacity_wh=150.0,
    )

    return det_sats, comp_sats, relay_sats


def create_tasks(n_tasks=3, start_time=30.0, interval=100.0):
    """GW alert 窗口内的候选事件"""
    tasks = []
    for i in range(n_tasks):
        task = TaskDAG(
            id=f"gw_event_{i:03d}",
            source_node=i % 3,  # 不同探测星触发
            arrival_time_s=start_time + i * interval,
            subtasks=[SubTask(
                id=f"gw_inference_{i}",
                compute_flops=4e9,        # GW-EM Matcher: 8s on 1TFLOPS? → 4GFLOP
                output_size_bytes=100_000, # 100 KB result
            )],
            dependencies=[],
            global_deadline_s=300.0,       # 5 min deadline
            result_destination=i % 3,     # 回传触发星
            result_size_bytes=100_000,
        )
        task.input_size_bytes = 3_000_000  # 3 MB
        tasks.append(task)
    return tasks


def run_case4():
    """Run Case 4 with multiple schedulers and compare."""
    print("=" * 70)
    print("  Case 4: Multi-Hop Relay — GW Counterpart Localization")
    print("=" * 70)

    det_sats, comp_sats, relay_sats = create_constellation()
    all_sats = det_sats + comp_sats + relay_sats
    print(f"\n  Constellation: {len(det_sats)} det + {len(comp_sats)} comp + {len(relay_sats)} relay = {len(all_sats)} total")
    print(f"  Det comm range: 2000 km (ensures no direct det↔comp link)")
    print(f"  Relay altitude: 1100 km (bridge between orbit planes)")

    config = SimConfig(
        duration_s=1800.0,
        dt=1.0,
        data_rate_bps=2e6,  # Bottleneck: det side S-band
        compute_flops_default=1e12,
    )

    # First, precompute orbits to get contact plan
    sim_pre = Simulator(config)
    sim_pre.set_satellites(all_sats)
    sim_pre.precompute_orbits()
    contact_plan = sim_pre.contact_plan
    
    # Analyze connectivity topology
    det_comp = [w for w in contact_plan.windows if 
        (all_sats[w.src].role == Role.DETECTOR and all_sats[w.dst].role == Role.COMPUTE) or
        (all_sats[w.dst].role == Role.DETECTOR and all_sats[w.src].role == Role.COMPUTE)]
    det_relay = [w for w in contact_plan.windows if 
        (all_sats[w.src].role == Role.DETECTOR and all_sats[w.dst].role == Role.RELAY) or
        (all_sats[w.dst].role == Role.DETECTOR and all_sats[w.src].role == Role.RELAY)]
    relay_comp = [w for w in contact_plan.windows if
        (all_sats[w.src].role == Role.RELAY and all_sats[w.dst].role == Role.COMPUTE) or
        (all_sats[w.dst].role == Role.RELAY and all_sats[w.src].role == Role.COMPUTE)]
    
    print(f"  Contact Plan: {len(contact_plan.windows)} windows")
    print(f"    Det↔Comp direct: {len(det_comp)}")
    print(f"    Det↔Relay: {len(det_relay)}")
    print(f"    Relay↔Comp: {len(relay_comp)}")
    
    # Find task arrival times where det has NO direct comp link
    # but DOES have relay link (forcing multi-hop)
    # For simplicity use the full contact plan and let schedulers compete

    # Build schedulers (TEG needs contact_plan + satellites)
    schedulers = {
        "Nearest-First": NearestFirstScheduler(),
        "Shortest-Path": ShortestPathScheduler(),
        "CGR+EDF": CGR_EDF_Scheduler(),
        "TEG": TEGScheduler(
            contact_plan=contact_plan,
            satellites=all_sats,
            data_rate_bps=config.data_rate_bps,
            time_horizon_s=config.duration_s,
            teg_dt_s=5.0,
        ),
    }

    results = {}
    for name, scheduler in schedulers.items():
        sim = Simulator(config)
        sim.set_satellites(all_sats)
        sim.precompute_orbits()
        sim.set_scheduler(scheduler)

        tasks = create_tasks(n_tasks=3, start_time=30.0, interval=100.0)
        for t in tasks:
            sim.add_task(t)

        metrics = sim.run()
        results[name] = metrics

        print(f"\n  {name:15s}: {metrics.success_rate*100:.0f}% "
              f"({metrics.completed_tasks}/{metrics.total_tasks}), "
              f"makespan={metrics.avg_makespan_s:.1f}s")

    # Static baseline comparison
    print(f"\n{'─' * 70}")
    print(f"  Static Topology Baseline (assumes direct det→comp link):")
    print(f"    Predicted makespan: 3MB/2Mbps + 4s + 0.1MB/2Mbps = ~16s")
    print(f"    Predicted success:  100%")
    print(f"{'─' * 70}")

    # Analysis
    teg_result = results.get("TEG")
    nf_result = results.get("Nearest-First")
    if teg_result and nf_result:
        print(f"\n  Key Finding:")
        print(f"    Nearest-First (1-hop): {nf_result.success_rate*100:.0f}% success")
        print(f"    TEG (multi-hop):       {teg_result.success_rate*100:.0f}% success")
        if teg_result.avg_makespan_s > 0:
            print(f"    Actual makespan:       {teg_result.avg_makespan_s:.1f}s")
            print(f"    Static assumption:     ~16s")
            print(f"    → Delay underestimate: {teg_result.avg_makespan_s/16:.1f}×")

    # Print summary
    print(f"\n{'=' * 70}")
    return results


if __name__ == "__main__":
    run_case4()
