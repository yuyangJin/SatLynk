"""
Case 6: 星座联邦学习 — 模型聚合的通信调度
================================================================
20 颗 EO 卫星协作训练模型。每轮各星上传 10MB 梯度到聚合节点。
关键瓶颈：跨面 ISL 间歇性，同面内永久可达。

对比: 静态模型(假设任意时刻全连通) vs SatLynk(Contact Plan 约束)
"""

import sys
import numpy as np

from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import generate_walker_delta, Role
from satlynk.task.dag import TaskDAG, SubTask
from satlynk.scheduler.interface import NearestFirstScheduler


def run_case6():
    print("=" * 70)
    print("  Case 6: Federated Learning — Aggregation Communication Delay")
    print("=" * 70)

    # 20 EO satellites, Walker(20/4/1)
    n_sats = 20
    n_planes = 4
    sats = generate_walker_delta(
        total_sats=n_sats, num_planes=n_planes, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE, prefix="SAT",
        compute_flops=1e12,
        max_comm_range_km=5000.0,
        power_solar_w=80.0,
        battery_capacity_wh=300.0,
    )
    # Node 0 is the aggregation server
    sats[0].id = "AGG-SERVER"

    print(f"\n  Constellation: {n_sats} sats, Walker({n_sats}/{n_planes}/1)")
    print(f"  Aggregation: node 0 (AGG-SERVER) collects gradients from all others")
    print(f"  Gradient size: 10 MB per satellite (compressed)")
    print(f"  Link: 50 Mbps ISL")

    config = SimConfig(
        duration_s=600.0, dt=1.0,
        data_rate_bps=50e6,
        compute_flops_default=1e12,
    )

    # Model one FL round as: each satellite sends 10MB gradient to aggregator
    # This is 19 tasks, all arriving at t=30 (after local training)
    tasks = []
    for i in range(1, n_sats):
        task = TaskDAG(
            id=f"gradient_{i:03d}",
            source_node=i,
            arrival_time_s=30.0,  # All finish local training simultaneously
            subtasks=[SubTask(
                id=f"agg_{i}",
                compute_flops=1e7,        # Trivial aggregation compute
                output_size_bytes=1000,   # Ack
            )],
            dependencies=[],
            global_deadline_s=120.0,
            result_destination=i,  # Ack back
            result_size_bytes=1000,
        )
        task.input_size_bytes = 10_000_000  # 10 MB gradient
        tasks.append(task)

    # --- SatLynk --- (use fixed assignment: all tasks execute on node 0)
    from satlynk.scheduler.interface import Schedule, TaskAssignment
    
    class FixedAggregatorScheduler:
        """All tasks must execute on the aggregator node (node 0)."""
        def on_task_arrive(self, task, env):
            return Schedule(assignments=[
                TaskAssignment(st.id, 0, env.current_time_s)
                for st in task.topological_order()
            ])
        def on_event(self, *a, **kw):
            return None

    sim = Simulator(config)
    sim.set_satellites(sats)
    sim.precompute_orbits()
    sim.set_scheduler(FixedAggregatorScheduler())
    for t in tasks:
        sim.add_task(t)
    metrics = sim.run()

    agg_time_satlynk = metrics.max_makespan_s  # Time until all gradients received

    # --- Static baseline ---
    # Ideal: 19 sats each send 10MB to node 0 simultaneously
    # Link rate 50 Mbps per link → if each has its own link: 10MB/50Mbps = 1.6s
    # But intra-plane sats (5/plane) share nothing; cross-plane need ISL
    # Static assumes all 19 can send in parallel: AoI = 1.6s
    # Reality: same-plane sats (4 others in plane 0) can send simultaneously
    # Cross-plane sats need window → serialized
    static_ideal = 10e6 * 8 / 50e6  # 1.6s per gradient transfer

    # With 19 tasks all to node 0: bandwidth into node 0 is the bottleneck
    # node 0 has 1 link per neighbor → max concurrent = number of neighbors with active links
    # In worst case all 19 serialize: 19 × 1.6s = 30.4s
    # In static best case (all parallel): 1.6s
    static_serial = static_ideal * (n_sats - 1)

    print(f"\n  Results:")
    print(f"    SatLynk: {metrics.completed_tasks}/{metrics.total_tasks} gradients received, "
          f"round time = {agg_time_satlynk:.1f}s")
    print(f"    Static (ideal parallel): {static_ideal:.1f}s")
    print(f"    Static (serial worst):   {static_serial:.1f}s")

    print(f"\n{'─' * 70}")
    print(f"  Analysis:")
    print(f"    Static ideal assumes all 19 links active simultaneously: {static_ideal:.1f}s")
    if metrics.completed_tasks < metrics.total_tasks:
        print(f"    SatLynk: only {metrics.completed_tasks}/{metrics.total_tasks} gradients arrive!")
        print(f"    → {metrics.total_tasks - metrics.completed_tasks} satellites have NO link to aggregator")
        print(f"    → Static model gives FALSE convergence guarantee")
        print(f"    → Real FL needs {600.0 / max(1, metrics.completed_tasks) * metrics.total_tasks:.0f}s+ per round")
    else:
        ratio = agg_time_satlynk / static_ideal if static_ideal > 0 else 0
        print(f"    SatLynk actual: {agg_time_satlynk:.1f}s")
        print(f"    → Static underestimates by {ratio:.1f}×")
    print(f"{'─' * 70}")
    print(f"\n{'=' * 70}")


if __name__ == "__main__":
    run_case6()
