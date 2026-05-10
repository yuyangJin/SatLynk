"""5-satellite Walker scenario — validates orbital propagation + auto contact plan."""

import sys
sys.path.insert(0, '/workspace')

import numpy as np
from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import (
    Satellite, Role, OrbitalElements, generate_walker_delta, 
    propagate_positions, orbital_period,
)
from satlynk.network.contact_plan import compute_contact_plan
from satlynk.task.dag import TaskDAG, SubTask
from satlynk.scheduler.interface import NearestFirstScheduler


def test_walker_5sat():
    """
    5-satellite scenario: 1 detector + 4 compute in Walker constellation.
    Validates that:
    1. Orbital propagation produces reasonable positions
    2. Contact plan is auto-generated with correct windows
    3. Tasks get scheduled and completed
    """
    print("=" * 60)
    print("SatLynk — 5-Satellite Walker Scenario")
    print("=" * 60)

    # --- Config ---
    duration_s = 600.0  # 10 minutes
    config = SimConfig(
        duration_s=duration_s,
        dt=1.0,
        data_rate_bps=10e6,
        compute_flops_default=8e9,  # 8 GFLOPS
    )

    # --- Generate constellation ---
    # 4 compute satellites in Walker(4/2/1) at 550km, 53° inclination
    compute_sats = generate_walker_delta(
        total_sats=4, num_planes=2, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE,
        prefix="COMP",
        compute_flops=8e9,
        power_solar_w=50, battery_capacity_wh=200,
        max_comm_range_km=5000,
    )

    # 1 detector satellite at 500km sun-synchronous
    detector = Satellite(
        id="DET-001", role=Role.DETECTOR,
        elements=OrbitalElements(
            semi_major_axis_km=6871,  # 500 km altitude
            inclination_deg=97.4,
            raan_deg=45.0,
            true_anomaly_deg=0.0,
        ),
        compute_flops=0,
        power_solar_w=10, battery_capacity_wh=40,
        max_comm_range_km=3000,
    )

    all_sats = [detector] + compute_sats  # detector = index 0, compute = 1-4
    
    print(f"\n[Constellation]")
    print(f"  Detector: {detector.id} (alt=500km, i=97.4°)")
    for i, sat in enumerate(compute_sats):
        print(f"  Compute {i+1}: {sat.id} (alt=550km, i=53°, RAAN={sat.elements.raan_deg:.0f}°, ν={sat.elements.true_anomaly_deg:.0f}°)")

    # --- Propagate orbits ---
    times = np.arange(0, duration_s + 1, 1.0)
    positions = propagate_positions(all_sats, times)
    
    print(f"\n[Orbital Propagation]")
    print(f"  Time steps: {len(times)}")
    print(f"  Position array shape: {positions.shape}")
    
    # Sanity check: altitude should be ~500-550 km
    for i, sat in enumerate(all_sats):
        r = np.linalg.norm(positions[i], axis=1)
        alt = r - 6371.0
        print(f"  {sat.id}: alt range [{alt.min():.0f}, {alt.max():.0f}] km")
    
    # --- Compute Contact Plan ---
    contact_plan = compute_contact_plan(
        all_sats, times, positions,
        data_rate_bps=config.data_rate_bps,
    )
    
    print(f"\n[Contact Plan]")
    print(f"  Total windows: {len(contact_plan)}")
    
    # Group by pair
    pair_counts = {}
    for w in contact_plan.windows:
        key = (w.src, w.dst)
        pair_counts[key] = pair_counts.get(key, 0) + 1
    
    for (src, dst), count in sorted(pair_counts.items()):
        src_name = all_sats[src].id
        dst_name = all_sats[dst].id
        windows = [w for w in contact_plan.windows if w.src == src and w.dst == dst]
        total_dur = sum(w.duration_s for w in windows)
        print(f"  {src_name} ↔ {dst_name}: {count} windows, total {total_dur:.0f}s contact time")

    # --- Setup Simulator ---
    sim = Simulator(config)
    sim.set_satellites(all_sats)
    sim.contact_plan = contact_plan
    sim.positions = positions
    sim.times = times
    sim._preload_link_events(contact_plan)
    sim.set_scheduler(NearestFirstScheduler())

    # --- Add tasks ---
    # Inject 3 tasks at different times
    for i, t_arrive in enumerate([10.0, 200.0, 400.0]):
        task = TaskDAG(
            id=f"task_{i:03d}",
            source_node=0,  # detector
            arrival_time_s=t_arrive,
            subtasks=[
                SubTask(id=f"infer_{i}", compute_flops=20e9, output_size_bytes=500_000),
            ],
            dependencies=[],
            global_deadline_s=120.0,
            result_destination=0,
            result_size_bytes=500_000,
        )
        task.input_size_bytes = 2_000_000  # 2 MB
        sim.add_task(task)

    # --- Run ---
    print(f"\n[Running simulation...]")
    metrics = sim.run()

    # --- Results ---
    print(f"\n[Results]")
    print(f"  Duration: {metrics.sim_duration_s:.0f}s")
    print(f"  Events processed: {metrics.events_processed}")
    print(f"  Tasks: {metrics.completed_tasks}/{metrics.total_tasks} completed")
    print(f"  Success rate: {metrics.success_rate:.0%}")
    if metrics.completed_tasks > 0:
        print(f"  Avg makespan: {metrics.avg_makespan_s:.1f}s")
        print(f"  Max makespan: {metrics.max_makespan_s:.1f}s")
    print(f"  Data transferred: {metrics.total_data_transferred_bytes/1e6:.1f} MB")
    print(f"  Min battery: {metrics.min_battery_pct:.1f}%")
    print(f"  Wall clock: {metrics.wall_clock_s:.3f}s")
    
    # Per-task results
    print(f"\n[Per-task Results]")
    for result in sim.metrics.task_results:
        print(f"  {result.task_id}: makespan={result.makespan_s:.1f}s, "
              f"success={result.success}")

    # --- Verification ---
    print(f"\n[Verification]")
    checks_passed = 0
    checks_total = 0
    
    # Check 1: At least some contact windows exist
    checks_total += 1
    if len(contact_plan) > 0:
        print(f"  ✓ Contact plan non-empty ({len(contact_plan)} windows)")
        checks_passed += 1
    else:
        print(f"  ✗ Contact plan is empty!")
    
    # Check 2: Orbits are at correct altitude
    checks_total += 1
    r_all = np.linalg.norm(positions, axis=2)  # (N, T)
    alt_all = r_all - 6371.0
    alt_ok = alt_all.min() > 400 and alt_all.max() < 700
    if alt_ok:
        print(f"  ✓ Altitudes in range [{alt_all.min():.0f}, {alt_all.max():.0f}] km")
        checks_passed += 1
    else:
        print(f"  ✗ Altitude out of range!")
    
    # Check 3: Tasks complete
    checks_total += 1
    if metrics.completed_tasks > 0:
        print(f"  ✓ {metrics.completed_tasks} task(s) completed")
        checks_passed += 1
    else:
        print(f"  ✗ No tasks completed")
    
    # Check 4: Energy stays reasonable
    checks_total += 1
    if metrics.min_battery_pct > 10:
        print(f"  ✓ Battery stayed above 10% (min={metrics.min_battery_pct:.1f}%)")
        checks_passed += 1
    else:
        print(f"  ✗ Battery dropped too low: {metrics.min_battery_pct:.1f}%")
    
    print(f"\n{'=' * 60}")
    print(f"Checks passed: {checks_passed}/{checks_total}")
    print(f"{'ALL PASSED ✓' if checks_passed == checks_total else 'SOME FAILED ✗'}")
    print(f"{'=' * 60}")
    
    return checks_passed == checks_total


if __name__ == "__main__":
    success = test_walker_5sat()
    sys.exit(0 if success else 1)
