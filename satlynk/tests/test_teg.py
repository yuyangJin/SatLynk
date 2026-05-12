"""Test Time-Expanded Graph (TEG) module.

Validates:
  1. TEG construction from ContactPlan
  2. Shortest path routing
  3. Earliest arrival computation
  4. Reachability analysis
  5. TEG scheduler integration
"""

from __future__ import annotations
import sys
sys.path.insert(0, '/workspace/satlynk')

from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import generate_walker_delta, Role
from satlynk.network.contact_plan import ContactPlan, ContactWindow
from satlynk.network.teg import TimeExpandedGraph, TEGNode, EdgeType
from satlynk.scheduler.teg_scheduler import TEGScheduler
from satlynk.task.dag import TaskDAG, SubTask


def test_teg_construction():
    """Test TEG builds correctly from a simple contact plan."""
    print("=" * 64)
    print("  TEG Construction Test")
    print("=" * 64)

    # Simple scenario: 3 nodes, 2 windows
    windows = [
        ContactWindow(src=0, dst=1, start_s=10, end_s=50,
                      avg_rate_bps=50e6, min_distance_km=500, max_distance_km=2000),
        ContactWindow(src=1, dst=2, start_s=30, end_s=80,
                      avg_rate_bps=50e6, min_distance_km=800, max_distance_km=3000),
    ]
    plan = ContactPlan(windows)

    teg = TimeExpandedGraph.from_contact_plan(
        contact_plan=plan,
        num_sats=3,
        horizon_s=100.0,
        dt_s=10.0,
        data_rate_bps=50e6,
    )

    stats = teg.graph_stats()
    print(f"\n  Nodes: {stats['num_nodes']} (expected: 3 sats × 11 slots = 33)")
    print(f"  Store edges: {stats['num_store_edges']} (expected: 3 × 10 = 30)")
    print(f"  Transfer edges: {stats['num_transfer_edges']}")
    print(f"  Total edges: {stats['num_edges']}")
    print(f"  Horizon: {stats['horizon_s']}s, dt={stats['dt_s']}s")

    assert stats['num_nodes'] == 33, f"Expected 33 nodes, got {stats['num_nodes']}"
    assert stats['num_store_edges'] == 30, f"Expected 30 store edges, got {stats['num_store_edges']}"
    # Window 0→1 [10,50]: slots 1,2,3,4 → 4 edges × 2 dirs = 8
    # Window 1→2 [30,80]: slots 3,4,5,6,7 → 5 edges × 2 dirs = 10
    assert stats['num_transfer_edges'] == 18, f"Expected 18 transfer edges, got {stats['num_transfer_edges']}"

    print("\n  ✓ Construction correct")
    return teg


def test_shortest_path(teg: TimeExpandedGraph):
    """Test shortest path routing on TEG."""
    print(f"\n{'=' * 64}")
    print("  TEG Shortest Path Test")
    print("=" * 64)

    # Path from node 0 to node 2 (must relay through node 1)
    path = teg.shortest_path(src_sat=0, dst_sat=2, earliest_departure_s=0.0)
    assert path is not None, "Expected a path from 0 to 2"

    print(f"\n  Path 0→2 (depart t=0):")
    print(f"    Hops: {path.hops}")
    print(f"    Time: {path.total_time_s}s")
    print(f"    Cost: {path.total_cost:.1f}")
    print(f"    Nodes: {path.nodes_visited}")

    # Must go through node 1 (no direct 0→2 link)
    assert 1 in path.nodes_visited, "Path must relay through node 1"
    assert path.hops >= 2, "Must have at least 2 transfer hops"

    # Path from 0 to 1 (direct link available from t=10)
    path_01 = teg.shortest_path(src_sat=0, dst_sat=1, earliest_departure_s=0.0)
    assert path_01 is not None, "Expected a path from 0 to 1"
    print(f"\n  Path 0→1 (depart t=0):")
    print(f"    Hops: {path_01.hops}")
    print(f"    Time: {path_01.total_time_s}s")
    print(f"    Nodes: {path_01.nodes_visited}")
    # Earliest transfer at slot 1 (t=10), arrives slot 2 (t=20)
    assert path_01.total_time_s <= 20.0, f"Expected ≤20s, got {path_01.total_time_s}"

    # No path with tight deadline
    path_impossible = teg.shortest_path(src_sat=0, dst_sat=2,
                                         earliest_departure_s=0.0,
                                         latest_arrival_s=20.0)
    assert path_impossible is None, "Should be no path within 20s"

    print("\n  ✓ Shortest path correct")


def test_earliest_arrival(teg: TimeExpandedGraph):
    """Test earliest arrival computation."""
    print(f"\n{'=' * 64}")
    print("  TEG Earliest Arrival Test")
    print("=" * 64)

    # 0→1: first window starts at t=10, transfer takes 1 slot (10s)
    t_01 = teg.earliest_arrival(src_sat=0, dst_sat=1, departure_s=0.0)
    print(f"\n  0→1 earliest arrival: t={t_01}s (expected: 20.0)")
    assert t_01 is not None
    assert t_01 == 20.0, f"Expected 20.0, got {t_01}"

    # 0→2: must go 0→1→2
    # 0→1 at t=20, then 1→2 (window starts at t=30) arrives t=40
    t_02 = teg.earliest_arrival(src_sat=0, dst_sat=2, departure_s=0.0)
    print(f"  0→2 earliest arrival: t={t_02}s (expected: 40.0)")
    assert t_02 is not None
    assert t_02 == 40.0, f"Expected 40.0, got {t_02}"

    # Departure after first window
    t_01_late = teg.earliest_arrival(src_sat=0, dst_sat=1, departure_s=55.0)
    print(f"  0→1 departure t=55: arrival={t_01_late} (expected: None, window ended at 50)")
    assert t_01_late is None, "Should be unreachable after window closes"

    print("\n  ✓ Earliest arrival correct")


def test_reachability(teg: TimeExpandedGraph):
    """Test reachability analysis."""
    print(f"\n{'=' * 64}")
    print("  TEG Reachability Test")
    print("=" * 64)

    # From node 0 at t=0, deadline 100s
    reachable = teg.reachable_nodes(src_sat=0, departure_s=0.0, deadline_s=100.0)
    print(f"\n  Reachable from node 0 (t=0, deadline=100s):")
    for sat, t_arrive in sorted(reachable.items()):
        print(f"    Node {sat}: arrives at t={t_arrive}s")

    assert 0 in reachable, "Source should be reachable"
    assert 1 in reachable, "Node 1 should be reachable"
    assert 2 in reachable, "Node 2 should be reachable (via 1)"
    assert reachable[0] == 0.0
    assert reachable[1] <= 20.0
    assert reachable[2] <= 40.0

    # From node 2 at t=0, deadline 20s (only self reachable)
    reachable_limited = teg.reachable_nodes(src_sat=2, departure_s=0.0, deadline_s=20.0)
    print(f"\n  Reachable from node 2 (t=0, deadline=20s):")
    for sat, t_arrive in sorted(reachable_limited.items()):
        print(f"    Node {sat}: arrives at t={t_arrive}s")

    # Node 2 has no outgoing window until 1→2 at t=30
    # But 1→2 is bidirectional, so 2→1 should also exist at t=30
    # With deadline 20s, only self is reachable
    assert 2 in reachable_limited
    # 1→2 window [30,80] means 2→1 also exists there, but starts at 30 > 20
    assert len(reachable_limited) == 1 or reachable_limited.get(1, 999) > 20

    print("\n  ✓ Reachability correct")


def test_teg_with_real_constellation():
    """Test TEG with a real Walker constellation (5 sats)."""
    print(f"\n{'=' * 64}")
    print("  TEG Real Constellation Test (5 satellites)")
    print("=" * 64)

    config = SimConfig(duration_s=600.0, dt=1.0, data_rate_bps=50e6)

    detectors = generate_walker_delta(
        total_sats=1, num_planes=1, phase_factor=0,
        altitude_km=535, inclination_deg=97.6,
        role=Role.DETECTOR, prefix='DET',
        compute_flops=0, power_solar_w=10,
        battery_capacity_wh=40, max_comm_range_km=3000,
    )
    computers = generate_walker_delta(
        total_sats=4, num_planes=2, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE, prefix='COMP',
        compute_flops=8e9, power_solar_w=50,
        battery_capacity_wh=200, max_comm_range_km=5000,
    )
    all_sats = detectors + computers

    sim = Simulator(config)
    sim.set_satellites(all_sats)
    sim.precompute_orbits()

    print(f"\n  Contact windows: {len(sim.contact_plan)}")
    for w in sim.contact_plan.windows:
        print(f"    {w}")

    # Build TEG with 10s granularity
    teg = TimeExpandedGraph.from_contact_plan(
        contact_plan=sim.contact_plan,
        num_sats=len(all_sats),
        horizon_s=600.0,
        dt_s=10.0,
        data_rate_bps=50e6,
    )

    stats = teg.graph_stats()
    print(f"\n  TEG stats:")
    print(f"    Nodes: {stats['num_nodes']}")
    print(f"    Edges: {stats['num_edges']}")
    print(f"    Transfer edges: {stats['num_transfer_edges']}")
    print(f"    Total transfer capacity: {stats['total_transfer_capacity_gb']:.2f} GB")

    # Test routing from detector(0) to any compute node
    reachable = teg.reachable_nodes(src_sat=0, departure_s=0.0, deadline_s=300.0)
    print(f"\n  From DET-0 (deadline 300s), reachable nodes: {list(reachable.keys())}")

    # Test earliest arrival to each compute node
    for comp_idx in range(1, 5):
        t_arrive = teg.earliest_arrival(src_sat=0, dst_sat=comp_idx, departure_s=30.0)
        status = f"t={t_arrive:.0f}s" if t_arrive is not None else "unreachable"
        print(f"    → COMP-{comp_idx}: {status}")

    print("\n  ✓ Real constellation TEG built and queried successfully")
    return sim, teg, all_sats


def test_teg_scheduler(sim, teg, all_sats):
    """Test TEG-based scheduler end-to-end."""
    print(f"\n{'=' * 64}")
    print("  TEG Scheduler Integration Test")
    print("=" * 64)

    # Create a new simulator instance for the test
    config = SimConfig(duration_s=600.0, dt=1.0, data_rate_bps=50e6, compute_flops_default=8e9)
    test_sim = Simulator(config)
    test_sim.set_satellites(all_sats)
    test_sim.precompute_orbits()

    # Create TEG scheduler
    teg_sched = TEGScheduler(
        contact_plan=test_sim.contact_plan,
        satellites=all_sats,
        data_rate_bps=50e6,
        time_horizon_s=600.0,
        teg_dt_s=10.0,
    )
    test_sim.set_scheduler(teg_sched)

    # Add tasks
    tasks = []
    for i in range(5):
        task = TaskDAG(
            id=f'task_{i:03d}', source_node=0, arrival_time_s=30.0 + i * 80,
            subtasks=[SubTask(id=f'infer_{i}', compute_flops=25e9, output_size_bytes=500_000)],
            dependencies=[], global_deadline_s=300.0,
            result_destination=0, result_size_bytes=500_000,
        )
        task.input_size_bytes = 3_000_000
        tasks.append(task)
        test_sim.add_task(task)

    metrics = test_sim.run()

    print(f"\n  Results:")
    print(f"    Tasks: {metrics.completed_tasks}/{metrics.total_tasks}")
    print(f"    Success rate: {metrics.success_rate*100:.0f}%")
    print(f"    Avg makespan: {metrics.avg_makespan_s:.1f}s")
    print(f"    Wall clock: {metrics.wall_clock_s*1000:.1f}ms")

    # Get routing details for first task
    routing = teg_sched.get_routing_info(tasks[0], 30.0)
    feasible_nodes = [nid for nid, info in routing.items() if info.get('feasible')]
    print(f"\n  Routing analysis for task_000:")
    print(f"    Feasible compute nodes: {feasible_nodes}")
    for nid in feasible_nodes[:3]:
        info = routing[nid]
        print(f"    Node {nid}: fwd={info.get('forward_time',0):.0f}s + "
              f"comp={info.get('compute_time',0):.1f}s + "
              f"ret={info.get('return_time',0):.0f}s = "
              f"total={info.get('total_time',0):.1f}s")

    assert metrics.success_rate > 0, "Should complete at least some tasks"
    print(f"\n  ✓ TEG scheduler works correctly")


def test_teg_vs_heuristics():
    """Compare TEG scheduler against heuristics on 15-sat scenario."""
    print(f"\n{'=' * 64}")
    print("  TEG vs Heuristics Comparison (15 satellites)")
    print("=" * 64)

    from satlynk.benchmark import make_scenario_15sat, run_single
    from satlynk.scheduler.interface import NearestFirstScheduler
    from satlynk.scheduler.heuristics import ShortestPathScheduler

    scenario = make_scenario_15sat()
    config = scenario['config']
    satellites = scenario['satellites']
    tasks = scenario['tasks']

    # Build shared contact plan
    ref_sim = Simulator(config)
    ref_sim.set_satellites(satellites)
    ref_sim.precompute_orbits()

    # TEG scheduler
    teg_sched = TEGScheduler(
        contact_plan=ref_sim.contact_plan,
        satellites=satellites,
        data_rate_bps=config.data_rate_bps,
        time_horizon_s=config.duration_s,
        teg_dt_s=10.0,
    )

    schedulers = {
        'Nearest-First': NearestFirstScheduler(),
        'Shortest-Path': ShortestPathScheduler(data_rate_bps=config.data_rate_bps),
        'TEG': teg_sched,
    }

    print(f"\n  Scenario: {scenario['name']}")
    print(f"  Satellites: {len(satellites)}, Tasks: {len(tasks)}")
    print(f"  Contact windows: {len(ref_sim.contact_plan)}")
    print()

    for name, sched in schedulers.items():
        result = run_single(scenario, name, sched)
        print(f"  {name:<16}: {result.success_rate*100:>5.1f}% "
              f"({result.completed_tasks}/{result.total_tasks}) "
              f"makespan={result.avg_makespan_s:.1f}s")

    print(f"\n  ✓ Comparison complete")


if __name__ == '__main__':
    print("\n" + "=" * 64)
    print("  SatLynk — Time-Expanded Graph (TEG) Tests")
    print("=" * 64)

    teg = test_teg_construction()
    test_shortest_path(teg)
    test_earliest_arrival(teg)
    test_reachability(teg)
    sim, teg_real, all_sats = test_teg_with_real_constellation()
    test_teg_scheduler(sim, teg_real, all_sats)
    test_teg_vs_heuristics()

    print(f"\n{'=' * 64}")
    print("  ALL TEG TESTS PASSED ✓")
    print("=" * 64)
