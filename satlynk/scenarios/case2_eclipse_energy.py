"""
Case 2: 地影穿越期瞬变响应 — 能耗约束下的磁星爆发判决
================================================================
磁星爆发持续 0.1-1s，必须在 <5s 内在轨判决。
部分计算星正在地影中电量低，贪心调度器不考虑能量 → 选了低电量星
→ 推理中电量跌破阈值 → SAFE_MODE → 任务失败。

关键对比：
- Nearest-First: 选最近节点（可能电量低）→ 部分任务失败
- Energy-Aware: 跳过低电量节点 → 全部成功
- Static Baseline: 看不到能耗 → 100% 成功（虚假乐观）
"""

import sys
import numpy as np

from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import (
    Satellite, Role, OrbitalElements, generate_walker_delta,
)
from satlynk.task.dag import TaskDAG, SubTask
from satlynk.scheduler.interface import NearestFirstScheduler
from satlynk.scheduler.heuristics import ShortestPathScheduler
from satlynk.scheduler.energy_aware import EnergyAwareScheduler
from satlynk.energy.battery import PowerProfile


def create_constellation():
    """
    10 颗计算星 + 3 颗探测星。
    计算星初始电量分布不均（模拟不同地影历史）。
    """
    # 天格探测星: 3颗
    det_sats = []
    for i in range(3):
        det_sats.append(Satellite(
            id=f"TG-{i+1:02d}",
            role=Role.DETECTOR,
            elements=OrbitalElements(
                semi_major_axis_km=6906.0,
                inclination_deg=97.4,
                raan_deg=0.0,
                true_anomaly_deg=i * 5.0,
            ),
            compute_flops=0,
            storage_bytes=int(4e9),
            max_comm_range_km=5000.0,
            power_solar_w=12.0,
            battery_capacity_wh=40.0,
        ))

    # 计算星: 10颗, 550km
    comp_sats = generate_walker_delta(
        total_sats=10, num_planes=2, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE, prefix="COMP",
        compute_flops=1e12,
        storage_bytes=int(64e9),
        max_comm_range_km=5000.0,
        power_solar_w=80.0,
        battery_capacity_wh=300.0,
    )

    return det_sats, comp_sats


def create_magnetar_tasks(n_tasks=5, start_time=30.0, interval=45.0):
    """
    5次磁星爆发，每45秒一次（模拟活跃期连续爆发）。
    从 TG-01 发出，需要快速判决。
    """
    tasks = []
    for i in range(n_tasks):
        task = TaskDAG(
            id=f"sgr_burst_{i:03d}",
            source_node=0,  # TG-01
            arrival_time_s=start_time + i * interval,
            subtasks=[SubTask(
                id=f"sgr_classify_{i}",
                compute_flops=1e8,            # 轻量分类器 0.1s on 1TFLOPS
                output_size_bytes=10_000,     # 10 KB
            )],
            dependencies=[],
            global_deadline_s=30.0,           # 30s deadline (relaxed for sim)
            result_destination=0,
            result_size_bytes=10_000,
        )
        task.input_size_bytes = 2_000_000  # 2 MB
        tasks.append(task)
    return tasks


def run_case2():
    """Run Case 2: Energy-constrained scheduling."""
    print("=" * 70)
    print("  Case 2: Eclipse Magnetar — Energy-Constrained Scheduling")
    print("=" * 70)

    det_sats, comp_sats = create_constellation()
    all_sats = det_sats + comp_sats
    n_det = len(det_sats)
    n_comp = len(comp_sats)
    print(f"\n  Constellation: {n_det} det + {n_comp} comp = {len(all_sats)} total")

    # Custom energy config: some nodes start with low battery
    # Simulates: 4 nodes just exited eclipse (low battery),
    #            3 nodes in sunlight (high), 3 nodes about to enter eclipse (medium)
    initial_battery = {
        0: 80.0, 1: 80.0, 2: 80.0,  # Detectors
        3: 28.0, 4: 26.0, 5: 30.0, 6: 27.0,   # Low battery (nodes 3-6)
        7: 75.0, 8: 72.0, 9: 70.0,              # High battery (sunlight)
        10: 55.0, 11: 52.0, 12: 50.0,           # Medium battery
    }

    config = SimConfig(
        duration_s=600.0,
        dt=1.0,
        data_rate_bps=2e6,
        compute_flops_default=1e12,
        compute_power_w=15.0,
        comm_power_w=5.0,
    )

    print(f"  Battery distribution:")
    print(f"    Low  (26-30%): nodes 3-6 (just exited eclipse)")
    print(f"    High (70-75%): nodes 7-9 (sunlight)")
    print(f"    Med  (50-55%): nodes 10-12")
    print(f"  LOW_POWER threshold: 30% (refuses new compute)")
    print(f"  Tasks: 5 magnetar bursts, 45s apart, 2MB input each")

    schedulers = {
        "Nearest-First": NearestFirstScheduler(),
        "Shortest-Path": ShortestPathScheduler(),
        "Energy-Aware": EnergyAwareScheduler(min_battery_pct=40.0),
    }

    results = {}
    for name, scheduler in schedulers.items():
        sim = Simulator(config)
        sim.set_satellites(all_sats)
        sim.precompute_orbits()

        # Override initial battery levels
        for node_id, pct in initial_battery.items():
            if node_id < len(all_sats):
                state = sim.energy.states[node_id]
                if state:
                    state.energy_j = state.capacity_j * pct / 100.0

        sim.set_scheduler(scheduler)

        tasks = create_magnetar_tasks(n_tasks=5, start_time=30.0, interval=45.0)
        for t in tasks:
            sim.add_task(t)

        metrics = sim.run()
        results[name] = metrics

        # Get min battery across compute nodes
        min_batt = min(
            sim.energy.get_battery_pct(i) for i in range(n_det, len(all_sats))
        )

        print(f"\n  {name:15s}: success={metrics.success_rate*100:.0f}% "
              f"({metrics.completed_tasks}/{metrics.total_tasks}), "
              f"makespan={metrics.avg_makespan_s:.1f}s, "
              f"min_battery={min_batt:.1f}%")

    # Comparison
    print(f"\n{'─' * 70}")
    print(f"  Static Topology Baseline (no energy modeling):")
    print(f"    Predicted success: 100% (energy constraints invisible)")
    print(f"{'─' * 70}")

    nf = results.get("Nearest-First")
    ea = results.get("Energy-Aware")
    if nf and ea:
        print(f"\n  Key Finding:")
        print(f"    Nearest-First: {nf.success_rate*100:.0f}% success")
        print(f"    Energy-Aware:  {ea.success_rate*100:.0f}% success")
        if nf.success_rate < ea.success_rate:
            gap = (ea.success_rate - nf.success_rate) * 100
            print(f"    Gap: +{gap:.0f}pp from energy awareness")
            print(f"    → C5 energy constraint kills {(1-nf.success_rate)*100:.0f}% of tasks under naive scheduling")
        else:
            print(f"    Note: No gap observed — need to tune energy parameters")

    print(f"\n{'=' * 70}")
    return results


if __name__ == "__main__":
    run_case2()
