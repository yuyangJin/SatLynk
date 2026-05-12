"""
Case 7: 碎片碰撞预警 — 紧急计算 + Deadline 约束
================================================================
空间碎片碰撞规避。发现碎片后必须在 TCA-30min 内完成:
观测数据传输 → 碰撞概率计算 → 决策回传。

对比在轨处理 vs 下传地面处理的延迟。
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


def create_constellation():
    # 监测星: 3颗 (光学碎片监测)
    det_sats = []
    for i in range(3):
        det_sats.append(Satellite(
            id=f"OBS-{i+1:02d}",
            role=Role.DETECTOR,
            elements=OrbitalElements(
                semi_major_axis_km=6921.0,  # 550km
                inclination_deg=97.4,
                raan_deg=i * 120.0,
                true_anomaly_deg=0.0,
            ),
            compute_flops=0,
            max_comm_range_km=5000.0,
            power_solar_w=20.0,
            battery_capacity_wh=60.0,
        ))

    # 计算星: 12颗
    comp_sats = generate_walker_delta(
        total_sats=12, num_planes=3, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE, prefix="COMP",
        compute_flops=1e12,
        max_comm_range_km=5000.0,
        power_solar_w=80.0,
        battery_capacity_wh=300.0,
    )
    return det_sats, comp_sats


def create_debris_tasks(n_tasks=5, start_time=60.0, interval=120.0):
    """碎片预警事件，deadline 紧迫。"""
    tasks = []
    for i in range(n_tasks):
        # Different deadlines simulate different TCA urgency
        deadline = 300.0 - i * 30  # 300s, 270s, 240s, 210s, 180s (越来越紧)
        task = TaskDAG(
            id=f"debris_{i:03d}",
            source_node=i % 3,
            arrival_time_s=start_time + i * interval,
            subtasks=[SubTask(
                id=f"collision_prob_{i}",
                compute_flops=5e9,           # 5s on 1 TFLOPS
                output_size_bytes=10_000,
            )],
            dependencies=[],
            global_deadline_s=deadline,
            result_destination=i % 3,  # 回传观测星
            result_size_bytes=10_000,
        )
        task.input_size_bytes = 500_000  # 500 KB
        tasks.append(task)
    return tasks


def run_case7():
    print("=" * 70)
    print("  Case 7: Debris Collision Warning — Deadline-Critical Computing")
    print("=" * 70)

    det_sats, comp_sats = create_constellation()
    all_sats = det_sats + comp_sats
    print(f"\n  Constellation: {len(det_sats)} obs + {len(comp_sats)} comp = {len(all_sats)} total")
    print(f"  Tasks: 5 debris alerts, deadlines 300→180s (increasingly urgent)")
    print(f"  Ground station alternative: avg 45 min wait for pass")

    config = SimConfig(
        duration_s=1200.0,
        dt=1.0,
        data_rate_bps=2e6,
        compute_flops_default=1e12,
    )

    schedulers = {
        "Nearest-First": NearestFirstScheduler(),
        "Shortest-Path": ShortestPathScheduler(),
        "CGR+EDF": CGR_EDF_Scheduler(),
    }

    results = {}
    for name, scheduler in schedulers.items():
        sim = Simulator(config)
        sim.set_satellites(all_sats)
        sim.precompute_orbits()
        sim.set_scheduler(scheduler)

        tasks = create_debris_tasks()
        for t in tasks:
            sim.add_task(t)

        metrics = sim.run()
        results[name] = metrics

        print(f"\n  {name:15s}: success={metrics.success_rate*100:.0f}% "
              f"({metrics.completed_tasks}/{metrics.total_tasks}), "
              f"avg_makespan={metrics.avg_makespan_s:.1f}s, "
              f"max_makespan={metrics.max_makespan_s:.1f}s")

    # Ground baseline
    print(f"\n{'─' * 70}")
    print(f"  Ground-Based Processing (traditional):")
    print(f"    Avg wait for GS pass: ~45 min (2700s)")
    print(f"    + downlink + processing + uplink: ~5 min")
    print(f"    Total: ~50 min → EXCEEDS all deadlines (180-300s)")
    print(f"{'─' * 70}")

    # Analysis
    best = max(results.values(), key=lambda m: m.success_rate)
    best_name = [k for k, v in results.items() if v == best][0]
    print(f"\n  Key Finding:")
    print(f"    Best in-orbit scheduler ({best_name}): {best.success_rate*100:.0f}% within deadline")
    print(f"    Ground processing: 0% within deadline (50min >> 5min limit)")
    print(f"    → In-orbit computing is NECESSARY, not just faster")

    print(f"\n{'=' * 70}")
    return results


if __name__ == "__main__":
    run_case7()
