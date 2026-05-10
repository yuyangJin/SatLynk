"""Generate viz export with real orbital positions for the 3D frontend."""

import sys

import numpy as np
from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import (
    Satellite, Role, OrbitalElements, generate_walker_delta, propagate_positions
)
from satlynk.network.contact_plan import compute_contact_plan
from satlynk.task.dag import TaskDAG, SubTask
from satlynk.scheduler.interface import NearestFirstScheduler


def generate_viz_data():
    """Generate a 5-sat scenario with real orbits for visualization."""
    
    config = SimConfig(
        duration_s=600.0,  # 10 minutes
        dt=1.0,
        data_rate_bps=10e6,
        compute_flops_default=8e9,
    )

    # 4 compute sats + 1 detector
    compute_sats = generate_walker_delta(
        total_sats=4, num_planes=2, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE, prefix="COMP",
        compute_flops=8e9,
        power_solar_w=50, battery_capacity_wh=200,
        max_comm_range_km=5000,
    )

    detector = Satellite(
        id="DET-001", role=Role.DETECTOR,
        elements=OrbitalElements(
            semi_major_axis_km=6871, inclination_deg=97.4,
            raan_deg=45.0, true_anomaly_deg=0.0,
        ),
        compute_flops=0,
        power_solar_w=10, battery_capacity_wh=40,
        max_comm_range_km=3000,
    )

    all_sats = [detector] + compute_sats

    # Setup simulator
    sim = Simulator(config)
    sim.set_satellites(all_sats)
    sim.precompute_orbits()
    sim.set_scheduler(NearestFirstScheduler())

    # Enable viz recording with 5s position interval (keep JSON small)
    viz = sim.enable_viz_recording(position_interval_s=5.0, energy_interval_s=5.0)
    viz.scenario_name = "walker_5sat_demo"

    # Add tasks
    for i, t_arrive in enumerate([10.0, 150.0, 300.0, 450.0]):
        task = TaskDAG(
            id=f"task_{i:03d}",
            source_node=0,
            arrival_time_s=t_arrive,
            subtasks=[SubTask(id=f"infer_{i}", compute_flops=20e9, output_size_bytes=500_000)],
            dependencies=[],
            global_deadline_s=180.0,
            result_destination=0,
            result_size_bytes=500_000,
        )
        task.input_size_bytes = 2_000_000
        sim.add_task(task)

    # Run
    metrics = sim.run()
    print(f"Tasks: {metrics.completed_tasks}/{metrics.total_tasks}, "
          f"Avg makespan: {metrics.avg_makespan_s:.1f}s")

    # Export
    output_path = "/workspace/oasis/viz/demo_export.json"
    viz.export_to_file(output_path, pretty=False)
    
    # Also export a pretty version for inspection
    viz.export_to_file("/workspace/oasis/viz/demo_export_pretty.json", pretty=True)
    
    # Stats
    json_str = viz.export_json(pretty=False)
    print(f"JSON size: {len(json_str)/1024:.1f} KB")
    print(f"Events: {len(viz.events)}")
    print(f"Transfers: {len(viz.transfers)}")
    print(f"Position samples: {len(viz.position_times)}")
    print(f"Exported to: {output_path}")


if __name__ == "__main__":
    generate_viz_data()
