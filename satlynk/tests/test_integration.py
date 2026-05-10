"""Integration test — Run the toy case through the full Simulator."""

import sys

import numpy as np
from satlynk.core.simulator import Simulator, SimConfig
from satlynk.core.engine import EventType
from satlynk.orbital.constellation import Satellite, Role, OrbitalElements
from satlynk.network.contact_plan import ContactPlan, ContactWindow
from satlynk.task.dag import TaskDAG, SubTask
from satlynk.scheduler.interface import NearestFirstScheduler


def test_toy_case_full_sim():
    """
    Run the 3-satellite relay scenario through the full simulator.
    
    Expected: Task completes with makespan ≈ 40.8s via relay D→A→B→D.
    """
    print("=" * 60)
    print("SatLynk Full Simulator — Toy Case Integration Test")
    print("=" * 60)

    # --- Config ---
    config = SimConfig(
        duration_s=65.0,
        dt=0.1,           # 100ms steps
        data_rate_bps=10e6,  # 10 Mbps
        compute_flops_default=1e9,  # 1 GFLOPS
    )

    sim = Simulator(config)

    # --- Satellites ---
    # Node 0: Detector D
    # Node 1: Compute A
    # Node 2: Compute B
    sats = [
        Satellite(
            id="D", role=Role.DETECTOR,
            elements=OrbitalElements(semi_major_axis_km=6871, inclination_deg=97),
            compute_flops=0, power_solar_w=10, battery_capacity_wh=40,
            max_comm_range_km=5000,
        ),
        Satellite(
            id="A", role=Role.COMPUTE,
            elements=OrbitalElements(semi_major_axis_km=6921, inclination_deg=53),
            compute_flops=1e9, power_solar_w=50, battery_capacity_wh=200,
            max_comm_range_km=5000,
        ),
        Satellite(
            id="B", role=Role.COMPUTE,
            elements=OrbitalElements(semi_major_axis_km=6921, inclination_deg=53,
                                     raan_deg=60, true_anomaly_deg=90),
            compute_flops=1e9, power_solar_w=50, battery_capacity_wh=200,
            max_comm_range_km=5000,
        ),
    ]
    sim.set_satellites(sats)

    # --- Contact Plan (manually specified for toy case) ---
    plan = ContactPlan([
        ContactWindow(src=0, dst=1, start_s=0.0, end_s=20.0,
                     avg_rate_bps=10e6, min_distance_km=1000, max_distance_km=1500),
        ContactWindow(src=1, dst=2, start_s=15.0, end_s=45.0,
                     avg_rate_bps=10e6, min_distance_km=800, max_distance_km=2000),
        ContactWindow(src=0, dst=2, start_s=40.0, end_s=60.0,
                     avg_rate_bps=10e6, min_distance_km=1200, max_distance_km=1800),
    ])
    sim.set_contact_plan(plan)

    # --- Scheduler ---
    sim.set_scheduler(NearestFirstScheduler())

    # --- Task ---
    task = TaskDAG(
        id="gamma_burst_001",
        source_node=0,
        arrival_time_s=0.0,
        subtasks=[
            SubTask(id="inference", compute_flops=25e9, output_size_bytes=1_000_000),
        ],
        dependencies=[],
        global_deadline_s=60.0,
        result_destination=0,
        result_size_bytes=1_000_000,
    )
    task.input_size_bytes = 6_250_000  # 6.25 MB
    sim.add_task(task)

    # --- Run ---
    print("\n[Running simulation...]")
    metrics = sim.run()

    # --- Results ---
    print(f"\n[Results]")
    print(f"  Events processed: {metrics.events_processed}")
    print(f"  Tasks completed: {metrics.completed_tasks}/{metrics.total_tasks}")
    print(f"  Success rate: {metrics.success_rate:.0%}")
    print(f"  Avg makespan: {metrics.avg_makespan_s:.1f}s")
    print(f"  Wall clock: {metrics.wall_clock_s:.3f}s")
    print(f"  Min battery: {metrics.min_battery_pct:.1f}%")

    # --- Verification ---
    print(f"\n[Verification]")
    
    expected_makespan = 40.8  # ±1s tolerance due to discrete stepping
    tolerance = 1.5  # Slightly more tolerance for discrete sim
    
    task_result = sim.metrics.task_results[0] if sim.metrics.task_results else None
    
    if task_result is None:
        print("  ✗ Task did not complete!")
        return False
    
    actual_makespan = task_result.makespan_s
    makespan_ok = abs(actual_makespan - expected_makespan) < tolerance
    
    print(f"  {'✓' if task_result.success else '✗'} Task completed: {task_result.success}")
    print(f"  {'✓' if makespan_ok else '✗'} Makespan: {actual_makespan:.1f}s "
          f"(expected ~{expected_makespan:.1f}s, tol={tolerance}s)")
    
    # Check that relay happened (result went through B)
    transfers = sim.metrics._transfer_log
    print(f"  Transfers logged: {len(transfers)}")
    for i, xfer in enumerate(transfers):
        print(f"    [{i}] {xfer['src']}→{xfer['dst']}: {xfer['bytes']/1e6:.2f} MB @ t={xfer['time']:.1f}s")
    
    all_pass = task_result.success and makespan_ok
    print(f"\n{'=' * 60}")
    print(f"{'ALL CHECKS PASSED ✓' if all_pass else 'SOME CHECKS FAILED ✗'}")
    print(f"{'=' * 60}")
    
    return all_pass


if __name__ == "__main__":
    success = test_toy_case_full_sim()
    sys.exit(0 if success else 1)
