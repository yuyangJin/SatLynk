"""Test viz export — Run toy case and export JSON for visualization."""

import sys
sys.path.insert(0, '/workspace')

import json
from oasis.core.simulator import Simulator, SimConfig
from oasis.orbital.constellation import Satellite, Role, OrbitalElements
from oasis.network.contact_plan import ContactPlan, ContactWindow
from oasis.task.dag import TaskDAG, SubTask


def test_viz_export():
    """Run toy case, export viz JSON, verify structure."""
    print("=" * 60)
    print("SatLynk Viz Export Test")
    print("=" * 60)

    # --- Setup (same as integration test) ---
    config = SimConfig(duration_s=65.0, dt=0.1, data_rate_bps=10e6)
    sim = Simulator(config)

    sats = [
        Satellite(id="D", role=Role.DETECTOR,
                  elements=OrbitalElements(semi_major_axis_km=6871, inclination_deg=97),
                  compute_flops=0, power_solar_w=10, battery_capacity_wh=40,
                  max_comm_range_km=5000),
        Satellite(id="A", role=Role.COMPUTE,
                  elements=OrbitalElements(semi_major_axis_km=6921, inclination_deg=53),
                  compute_flops=1e9, power_solar_w=50, battery_capacity_wh=200,
                  max_comm_range_km=5000),
        Satellite(id="B", role=Role.COMPUTE,
                  elements=OrbitalElements(semi_major_axis_km=6921, inclination_deg=53,
                                           raan_deg=60, true_anomaly_deg=90),
                  compute_flops=1e9, power_solar_w=50, battery_capacity_wh=200,
                  max_comm_range_km=5000),
    ]
    sim.set_satellites(sats)

    plan = ContactPlan([
        ContactWindow(src=0, dst=1, start_s=0.0, end_s=20.0,
                     avg_rate_bps=10e6, min_distance_km=1000, max_distance_km=1500),
        ContactWindow(src=1, dst=2, start_s=15.0, end_s=45.0,
                     avg_rate_bps=10e6, min_distance_km=800, max_distance_km=2000),
        ContactWindow(src=0, dst=2, start_s=40.0, end_s=60.0,
                     avg_rate_bps=10e6, min_distance_km=1200, max_distance_km=1800),
    ])
    sim.set_contact_plan(plan)

    # Enable viz recording
    viz = sim.enable_viz_recording(position_interval_s=1.0, energy_interval_s=1.0)
    viz.scenario_name = "tiange_3sat_toy"

    # Add task
    task = TaskDAG(
        id="gamma_burst_001",
        source_node=0, arrival_time_s=0.0,
        subtasks=[SubTask(id="inference", compute_flops=25e9, output_size_bytes=1_000_000)],
        dependencies=[],
        global_deadline_s=60.0, result_destination=0, result_size_bytes=1_000_000,
    )
    task.input_size_bytes = 6_250_000
    sim.add_task(task)

    # --- Run ---
    print("\n[Running simulation...]")
    metrics = sim.run()
    print(f"  Tasks: {metrics.completed_tasks}/{metrics.total_tasks}")
    print(f"  Makespan: {metrics.avg_makespan_s:.1f}s")

    # --- Export ---
    output_path = "/workspace/oasis/viz/toy_case_export.json"
    viz.export_to_file(output_path, pretty=True)
    print(f"\n[Exported to: {output_path}]")

    # --- Verify JSON structure ---
    with open(output_path, 'r') as f:
        data = json.load(f)

    print(f"\n[JSON Structure Verification]")
    
    checks = []
    
    # Scenario
    assert data["scenario"]["name"] == "tiange_3sat_toy"
    checks.append(("scenario.name", True))
    
    # Satellites
    assert len(data["satellites"]) == 3
    assert data["satellites"][0]["role"] == "detector"
    assert data["satellites"][1]["role"] == "compute"
    checks.append(("satellites (3 entries)", True))
    
    # Positions
    assert len(data["positions"]["times"]) > 0
    assert len(data["positions"]["data"]) == 3
    assert len(data["positions"]["data"][0]) == len(data["positions"]["times"])
    checks.append((f"positions ({len(data['positions']['times'])} samples)", True))
    
    # Contact windows
    assert len(data["contact_windows"]) == 3
    checks.append(("contact_windows (3)", True))
    
    # Events
    assert len(data["events"]) > 0
    event_types = set(e["type"] for e in data["events"])
    checks.append((f"events ({len(data['events'])} entries, types: {event_types})", True))
    
    # Transfers
    assert len(data["transfers"]) >= 3  # input + relay + result
    for xfer in data["transfers"]:
        assert xfer["end"] > xfer["start"], f"Transfer end <= start: {xfer}"
    checks.append((f"transfers ({len(data['transfers'])} entries, all have valid time)", True))
    
    # Compute jobs
    assert len(data["compute_jobs"]) >= 1
    for job in data["compute_jobs"]:
        assert job["end"] > job["start"]
    checks.append((f"compute_jobs ({len(data['compute_jobs'])} entries)", True))
    
    # Energy
    assert len(data["energy"]["times"]) > 0
    assert "0" in data["energy"]["data"]
    checks.append((f"energy ({len(data['energy']['times'])} samples)", True))
    
    for name, ok in checks:
        print(f"  {'✓' if ok else '✗'} {name}")
    
    # Print summary
    print(f"\n[Export Summary]")
    json_str = viz.export_json(pretty=False)
    print(f"  JSON size: {len(json_str):,} bytes ({len(json_str)/1024:.1f} KB)")
    print(f"  Events: {len(data['events'])}")
    print(f"  Transfers: {len(data['transfers'])}")
    print(f"  Compute jobs: {len(data['compute_jobs'])}")
    print(f"  Position samples: {len(data['positions']['times'])}")
    print(f"  Energy samples: {len(data['energy']['times'])}")
    
    # Print event timeline
    print(f"\n[Event Timeline]")
    for e in data["events"]:
        print(f"  t={e['t']:6.1f}  {e['type']:16s}  {e['detail']}")
    
    print(f"\n{'=' * 60}")
    print(f"ALL CHECKS PASSED ✓")
    print(f"{'=' * 60}")
    return True


if __name__ == "__main__":
    success = test_viz_export()
    sys.exit(0 if success else 1)
