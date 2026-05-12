"""
Case 3: 多模型热切换 — 搬数据 vs 搬权重的相变 (OBS3)
================================================================
SolarFlare-CNN (500 MB) 只在 3 颗计算星上有缓存。
6 次太阳耀斑连续触发。对比：
- 无权重感知：所有任务排队等有模型的 3 颗星 → 串行
- 有权重感知：去远处有模型的星（远但有模型比近但没模型快）
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


def create_constellation():
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
            max_comm_range_km=5000.0,
            power_solar_w=12.0,
            battery_capacity_wh=40.0,
        ))

    comp_sats = generate_walker_delta(
        total_sats=15, num_planes=3, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE, prefix="COMP",
        compute_flops=1e12,
        storage_bytes=int(64e9),
        max_comm_range_km=5000.0,
        power_solar_w=80.0,
        battery_capacity_wh=300.0,
    )
    return det_sats, comp_sats


def create_flare_tasks(n_tasks=6, start_time=50.0, interval=30.0):
    tasks = []
    for i in range(n_tasks):
        task = TaskDAG(
            id=f"flare_{i:03d}",
            source_node=0,
            arrival_time_s=start_time + i * interval,
            subtasks=[SubTask(
                id=f"flare_classify_{i}",
                compute_flops=2e8,           # 0.2s on 1TFLOPS
                output_size_bytes=50_000,
                required_model="solar_flare_cnn",  # C4: must have model
            )],
            dependencies=[],
            global_deadline_s=60.0,
            result_destination=0,
            result_size_bytes=50_000,
        )
        task.input_size_bytes = 500_000  # 500 KB
        tasks.append(task)
    return tasks


def run_case3():
    print("=" * 70)
    print("  Case 3: Weight Migration — Move Data vs Move Model (OBS3)")
    print("=" * 70)

    det_sats, comp_sats = create_constellation()
    all_sats = det_sats + comp_sats
    n_det = len(det_sats)
    print(f"\n  Constellation: {n_det} det + {len(comp_sats)} comp = {len(all_sats)} total")
    print(f"  Model: solar_flare_cnn (500 MB), cached on nodes 3, 7, 11 only")
    print(f"  Tasks: 6 solar flares, 30s apart, 500KB input each")

    config = SimConfig(
        duration_s=600.0,
        dt=1.0,
        data_rate_bps=50e6,  # comp↔comp 50 Mbps
        compute_flops_default=1e12,
    )

    # Model: cached on only 3 out of 15 comp nodes
    model_nodes = [3, 7, 11]  # node indices (offset by n_det=3 → comp nodes 0,4,8)
    model_name = "solar_flare_cnn"
    model_size = 500_000_000  # 500 MB

    schedulers = {
        "Nearest-First": NearestFirstScheduler(),
        "Shortest-Path": ShortestPathScheduler(),
    }

    results = {}
    for name, scheduler in schedulers.items():
        sim = Simulator(config)
        sim.set_satellites(all_sats)
        sim.precompute_orbits()

        # Register model and pre-cache on selected nodes
        sim.weight_mgr.register_model(model_name, model_size)
        for nid in model_nodes:
            sim.weight_mgr.cache_weight(nid, model_name, t=0.0)

        sim.set_scheduler(scheduler)

        tasks = create_flare_tasks(n_tasks=6, start_time=50.0, interval=30.0)
        for t in tasks:
            sim.add_task(t)

        metrics = sim.run()
        results[name] = metrics

        # Count weight migrations
        migrations = sum(1 for tid, xfer in sim._active_transfers.items()
                        if 'weight' in xfer.purpose) if hasattr(sim, '_active_transfers') else 0

        print(f"\n  {name:15s}: success={metrics.success_rate*100:.0f}% "
              f"({metrics.completed_tasks}/{metrics.total_tasks}), "
              f"makespan={metrics.avg_makespan_s:.1f}s")

    # Static baseline
    print(f"\n{'─' * 70}")
    print(f"  Static Baseline (no weight constraint):")
    static_makespan = 0.5e6 * 8 / 50e6 + 0.2  # 500KB/50Mbps + 0.2s compute
    print(f"    Predicted makespan: {static_makespan:.2f}s (assumes any node can compute)")
    print(f"    Predicted success: 100%")
    print(f"{'─' * 70}")

    print(f"\n  Key Insight (OBS3):")
    print(f"    Model migration time: 500MB / 50Mbps = 80s")
    print(f"    Remote data transfer: 500KB / 50Mbps = 0.08s")
    print(f"    → For single task: move data (0.08s) >> move model (80s)")
    print(f"    → For 6+ repeated tasks: move model once, save 6×(remote overhead)")

    print(f"\n{'=' * 70}")
    return results


if __name__ == "__main__":
    run_case3()
