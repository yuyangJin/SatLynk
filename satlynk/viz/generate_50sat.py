"""Generate 50-satellite scenario for visualization."""

import sys

import numpy as np
from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import (
    Satellite, Role, OrbitalElements, generate_walker_delta
)
from satlynk.task.dag import TaskDAG, SubTask
from satlynk.scheduler.interface import NearestFirstScheduler


def generate_50sat():
    config = SimConfig(
        duration_s=900.0,      # 15 minutes
        dt=1.0,
        data_rate_bps=50e6,    # 50 Mbps (faster links for 50-star)
        compute_flops_default=8e9,
    )

    # 36 compute sats: Walker(36/6/1) at 550km, 53°
    compute_sats = generate_walker_delta(
        total_sats=36, num_planes=6, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE, prefix="COMP",
        compute_flops=8e9,
        power_solar_w=50, battery_capacity_wh=200,
        max_comm_range_km=4000,
    )

    # 8 detector sats: Walker(8/2/0) at 500km, 97.4° (sun-sync)
    detector_sats = generate_walker_delta(
        total_sats=8, num_planes=2, phase_factor=0,
        altitude_km=500, inclination_deg=97.4,
        role=Role.DETECTOR, prefix="DET",
        compute_flops=0,
        power_solar_w=10, battery_capacity_wh=40,
        max_comm_range_km=3000,
    )

    # 6 relay sats: Walker(6/3/1) at 1100km, 65°
    relay_sats = generate_walker_delta(
        total_sats=6, num_planes=3, phase_factor=1,
        altitude_km=1100, inclination_deg=65.0,
        role=Role.RELAY, prefix="RLY",
        compute_flops=0,
        power_solar_w=100, battery_capacity_wh=500,
        max_comm_range_km=8000,
    )

    all_sats = detector_sats + compute_sats + relay_sats  # det=0-7, comp=8-43, relay=44-49
    print(f"Total satellites: {len(all_sats)} (det={len(detector_sats)}, comp={len(compute_sats)}, relay={len(relay_sats)})")

    # Setup simulator
    sim = Simulator(config)
    sim.set_satellites(all_sats)
    
    print("Precomputing orbits and contact plan...")
    sim.precompute_orbits()
    print(f"Contact plan: {len(sim.contact_plan)} windows")
    
    sim.set_scheduler(NearestFirstScheduler())

    # Enable viz (sample every 3s to keep JSON manageable)
    viz = sim.enable_viz_recording(position_interval_s=3.0, energy_interval_s=10.0)
    viz.scenario_name = "50sat_constellation"

    # Add tasks from various detectors
    import random
    random.seed(42)
    task_count = 0
    for t_arrive in range(30, 850, 40):  # ~20 tasks over 15 min
        det_idx = random.randint(0, 7)  # Random detector
        task = TaskDAG(
            id=f"task_{task_count:03d}",
            source_node=det_idx,
            arrival_time_s=float(t_arrive),
            subtasks=[SubTask(
                id=f"infer_{task_count}",
                compute_flops=random.uniform(10e9, 50e9),
                output_size_bytes=random.randint(200_000, 2_000_000),
            )],
            dependencies=[],
            global_deadline_s=300.0,
            result_destination=det_idx,
            result_size_bytes=random.randint(100_000, 1_000_000),
        )
        task.input_size_bytes = random.randint(1_000_000, 8_000_000)
        sim.add_task(task)
        task_count += 1

    print(f"Tasks scheduled: {task_count}")
    print("Running simulation...")
    metrics = sim.run()
    
    print(f"\n[Results]")
    print(f"  Completed: {metrics.completed_tasks}/{metrics.total_tasks}")
    print(f"  Success rate: {metrics.success_rate:.0%}")
    print(f"  Avg makespan: {metrics.avg_makespan_s:.1f}s")
    print(f"  Wall clock: {metrics.wall_clock_s:.3f}s")
    print(f"  Events processed: {metrics.events_processed}")

    # Export
    output = "/workspace/oasis/viz/50sat_export.json"
    viz.export_to_file(output, pretty=False)
    json_size = len(viz.export_json(pretty=False))
    print(f"\n  JSON size: {json_size/1024:.1f} KB")
    print(f"  Events: {len(viz.events)}")
    print(f"  Transfers: {len(viz.transfers)}")
    print(f"  Position samples: {len(viz.position_times)}")
    print(f"  Exported to: {output}")
    
    return output


if __name__ == "__main__":
    generate_50sat()
