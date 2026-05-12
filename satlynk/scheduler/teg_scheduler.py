"""TEG-based Scheduler — Uses Time-Expanded Graph for optimal routing.

The TEG scheduler pre-builds the time-expanded graph and uses it to find
the minimum-time (or minimum-cost) route for each task, considering:
  - Forward path: source → compute node (input transfer)
  - Compute delay at the selected node
  - Return path: compute node → destination (result transfer)

Advantages over heuristic schedulers:
  - Globally optimal routing (considers all possible multi-hop paths)
  - Aware of bandwidth contention (capacity constraints on edges)
  - Can evaluate ALL candidate nodes in one graph search
"""

from __future__ import annotations

from typing import Optional, Dict, List
import numpy as np

from satlynk.task.dag import TaskDAG
from satlynk.network.teg import TimeExpandedGraph, TEGPath
from satlynk.network.contact_plan import ContactPlan
from satlynk.scheduler.interface import (
    Scheduler, Schedule, TaskAssignment, EnvSnapshot, NodeSnapshot,
)


class TEGScheduler:
    """
    Scheduler that uses the Time-Expanded Graph for routing decisions.
    
    Strategy:
        For each task, evaluate all compute nodes via TEG routing:
        1. Find shortest path src → node (forward)
        2. Add compute time at node
        3. Find shortest path node → dest (return)
        4. Pick the node with minimum total end-to-end time
    
    This is the first scheduler that truly leverages the full TEG structure,
    enabling multi-hop relay paths that no heuristic would find.
    """

    def __init__(self, contact_plan: ContactPlan, satellites: list,
                 data_rate_bps: float = 50e6, time_horizon_s: float = 1800.0,
                 teg_dt_s: float = 10.0):
        """
        Args:
            contact_plan: Precomputed contact windows
            satellites: List of satellite objects
            data_rate_bps: Link data rate
            time_horizon_s: Planning horizon
            teg_dt_s: TEG time slot granularity (smaller = more precise but slower)
        """
        self.satellites = satellites
        self.data_rate_bps = data_rate_bps
        self.time_horizon_s = time_horizon_s

        # Build TEG
        self.teg = TimeExpandedGraph.from_contact_plan(
            contact_plan=contact_plan,
            num_sats=len(satellites),
            horizon_s=time_horizon_s,
            dt_s=teg_dt_s,
            data_rate_bps=data_rate_bps,
        )

        # Identify compute nodes
        self._compute_nodes = [
            i for i, sat in enumerate(satellites)
            if sat.role.value in ("compute", "hybrid")
        ]

    def on_task_arrive(self, task: TaskDAG, env: EnvSnapshot) -> Schedule:
        """Find optimal assignment using TEG routing."""
        source = task.source_node
        dest = task.result_destination if task.result_destination >= 0 else source
        t_now = env.current_time_s
        input_size = getattr(task, 'input_size_bytes', 0)
        result_size = task.result_size_bytes
        deadline = task.global_deadline_s or self.time_horizon_s
        deadline_abs = t_now + deadline

        best_node = None
        best_completion = float('inf')

        for nid in self._compute_nodes:
            # Forward path: source → compute node
            if nid == source:
                t_input_done = t_now
            else:
                t_arrive_at_node = self.teg.earliest_arrival(
                    src_sat=source, dst_sat=nid,
                    departure_s=t_now,
                    data_bytes=input_size,
                )
                if t_arrive_at_node is None:
                    continue
                t_input_done = t_arrive_at_node

            # Compute time
            flops = self.satellites[nid].compute_flops
            if flops <= 0:
                flops = 8e9
            t_compute = task.subtasks[0].compute_flops / flops
            t_compute_done = t_input_done + t_compute

            # Check if compute finishes before deadline
            if t_compute_done >= deadline_abs:
                continue

            # Return path: compute node → destination
            if nid == dest:
                t_completion = t_compute_done
            else:
                t_arrive_at_dest = self.teg.earliest_arrival(
                    src_sat=nid, dst_sat=dest,
                    departure_s=t_compute_done,
                    data_bytes=result_size,
                )
                if t_arrive_at_dest is None:
                    continue
                t_completion = t_arrive_at_dest

            # Check deadline
            if t_completion > deadline_abs:
                continue

            if t_completion < best_completion:
                best_completion = t_completion
                best_node = nid

        # Fallback: nearest node
        if best_node is None:
            source_pos = env.nodes[source].position
            compute_nodes = [
                n for n in env.nodes.values()
                if n.role == "compute" and n.compute_flops > 0
            ]
            if compute_nodes:
                best_node = min(compute_nodes,
                               key=lambda n: np.linalg.norm(n.position - source_pos)).node_id
            else:
                best_node = source

        return Schedule(assignments=[
            TaskAssignment(st.id, best_node, env.current_time_s)
            for st in task.topological_order()
        ])

    def on_event(self, event_type, payload, env):
        return None

    def get_routing_info(self, task: TaskDAG, t_now: float) -> Dict:
        """
        Get detailed routing information for a task (for analysis/viz).
        
        Returns dict with forward/return paths and timing breakdown.
        """
        source = task.source_node
        dest = task.result_destination if task.result_destination >= 0 else source
        input_size = getattr(task, 'input_size_bytes', 0)
        result_size = task.result_size_bytes

        results = {}
        for nid in self._compute_nodes:
            info = {'node': nid, 'feasible': False}

            # Forward
            if nid == source:
                info['forward_time'] = 0
                info['forward_path'] = [source]
                t_input_done = t_now
            else:
                fwd_path = self.teg.shortest_path(source, nid, t_now,
                                                  data_bytes=input_size)
                if fwd_path is None:
                    results[nid] = info
                    continue
                info['forward_time'] = fwd_path.total_time_s
                info['forward_path'] = fwd_path.nodes_visited
                info['forward_hops'] = fwd_path.hops
                t_input_done = t_now + fwd_path.total_time_s

            # Compute
            flops = self.satellites[nid].compute_flops or 8e9
            t_compute = task.subtasks[0].compute_flops / flops
            info['compute_time'] = t_compute
            t_compute_done = t_input_done + t_compute

            # Return
            if nid == dest:
                info['return_time'] = 0
                info['return_path'] = [dest]
                info['total_time'] = t_compute_done - t_now
            else:
                ret_path = self.teg.shortest_path(nid, dest, t_compute_done,
                                                  data_bytes=result_size)
                if ret_path is None:
                    results[nid] = info
                    continue
                info['return_time'] = ret_path.total_time_s
                info['return_path'] = ret_path.nodes_visited
                info['return_hops'] = ret_path.hops
                info['total_time'] = (t_compute_done + ret_path.total_time_s) - t_now

            info['feasible'] = True
            results[nid] = info

        return results
