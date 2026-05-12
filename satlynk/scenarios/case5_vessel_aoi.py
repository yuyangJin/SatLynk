"""
Case 5: 船舶检测 — 分布式推理与信息新鲜度 (AoI)
================================================================
EO 星拍摄图像，切片分发给邻居星推理。
AoI = 最后一块结果回传时刻 - 拍摄时刻。

对比: 静态拓扑假设 (链路永在) vs SatLynk (Contact Plan 约束)
在不同星座密度下的 peak AoI。
"""

import sys
import numpy as np

from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import (
    Satellite, Role, OrbitalElements, generate_walker_delta,
)
from satlynk.task.dag import TaskDAG, SubTask
from satlynk.scheduler.interface import NearestFirstScheduler


def run_aoi_sweep():
    """Sweep constellation density and measure AoI."""
    print("=" * 70)
    print("  Case 5: Vessel Detection — AoI vs Constellation Density")
    print("=" * 70)
    print(f"\n  Task: EO satellite captures 100MB image → split into 4 blocks")
    print(f"       → distribute to neighbors for YOLOv8 inference")
    print(f"       → AoI = time until all results returned")
    print(f"  Link: 50 Mbps ISL, blocks = 25 MB each")
    print(f"  Inference: 2s per block on 1 TFLOPS")

    densities = [8, 12, 20, 30, 40]
    results_static = []
    results_satlynk = []

    for n_sats in densities:
        # Generate constellation
        n_planes = max(2, n_sats // 5)
        sats = generate_walker_delta(
            total_sats=n_sats, num_planes=n_planes, phase_factor=1,
            altitude_km=550, inclination_deg=53.0,
            role=Role.COMPUTE, prefix="SAT",
            compute_flops=1e12,
            max_comm_range_km=5000.0,
            power_solar_w=80.0,
            battery_capacity_wh=300.0,
        )
        # First satellite is the "EO capture" node
        sats[0].role = Role.DETECTOR
        sats[0].id = "EO-01"

        config = SimConfig(
            duration_s=300.0,
            dt=1.0,
            data_rate_bps=50e6,  # 50 Mbps ISL
            compute_flops_default=1e12,
        )

        # Create 4 tasks (simulating 4 image blocks distributed to neighbors)
        tasks = []
        for i in range(4):
            task = TaskDAG(
                id=f"block_{i:03d}",
                source_node=0,  # EO-01
                arrival_time_s=10.0,  # All captured at same time
                subtasks=[SubTask(
                    id=f"yolo_{i}",
                    compute_flops=2e9,       # 2s on 1 TFLOPS
                    output_size_bytes=10_000, # 10 KB result
                )],
                dependencies=[],
                global_deadline_s=120.0,
                result_destination=0,
                result_size_bytes=10_000,
            )
            task.input_size_bytes = 25_000_000  # 25 MB per block
            tasks.append(task)

        # --- SatLynk simulation ---
        sim = Simulator(config)
        sim.set_satellites(sats)
        sim.precompute_orbits()
        sim.set_scheduler(NearestFirstScheduler())
        for t in tasks:
            sim.add_task(t)
        metrics = sim.run()

        # AoI = max makespan (time from capture to last result)
        aoi_satlynk = metrics.max_makespan_s if metrics.completed_tasks > 0 else float('inf')
        success_satlynk = metrics.completed_tasks

        # --- Static baseline (assumes all links always active, no contention) ---
        # Transfer: 25MB / 50Mbps = 4s, Compute: 2s, Return: negligible
        # If 4 blocks go to 4 different nodes (ideal): AoI = 4+2+0 = 6s
        # If all go to 1 node (contention): 4*4+2+0 = 18s (serial)
        # With Nearest-First in static: usually 1 node → 4+2 = 6s per block serial
        # But bandwidth contention means 4 blocks share: 25MB*4 / 50Mbps = 16s total
        n_reachable = min(4, n_sats - 1)  # How many neighbors
        if n_reachable >= 4:
            # Can distribute to 4 different nodes
            aoi_static = 25e6 * 8 / 50e6 + 2.0  # 4s transfer + 2s compute = 6s
        else:
            # Some blocks queue
            serial_factor = 4.0 / max(1, n_reachable)
            aoi_static = (25e6 * 8 / 50e6) * serial_factor + 2.0

        results_static.append(aoi_static)
        results_satlynk.append(aoi_satlynk)

        status = f"{success_satlynk}/4 ok" if success_satlynk < 4 else "all ok"
        print(f"\n  {n_sats:2d} sats ({n_planes} planes): "
              f"SatLynk AoI={aoi_satlynk:.1f}s ({status}), "
              f"Static AoI={aoi_static:.1f}s")

    # Summary
    print(f"\n{'─' * 70}")
    print(f"  Density Sweep Summary:")
    print(f"  {'Sats':>5} | {'Static AoI':>10} | {'SatLynk AoI':>11} | {'Ratio':>6}")
    print(f"  {'─'*5}-+-{'─'*10}-+-{'─'*11}-+-{'─'*6}")
    for i, n in enumerate(densities):
        ratio = results_satlynk[i] / results_static[i] if results_static[i] > 0 else 0
        print(f"  {n:5d} | {results_static[i]:8.1f}s | {results_satlynk[i]:9.1f}s | {ratio:5.1f}×")
    print(f"{'─' * 70}")

    print(f"\n  Key Finding:")
    avg_ratio = np.mean([s/st for s, st in zip(results_satlynk, results_static) if st > 0 and s < 999])
    print(f"    Average underestimate by static model: {avg_ratio:.1f}×")
    print(f"    Static model assumes all neighbors always reachable")
    print(f"    SatLynk shows actual AoI depends on Contact Plan windows")

    print(f"\n{'=' * 70}")


if __name__ == "__main__":
    run_aoi_sweep()
