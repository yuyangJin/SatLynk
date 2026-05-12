"""Load-Balanced Scheduler — Avoids bandwidth contention.

Extends Shortest-Path by tracking per-link utilization.
When multiple tasks compete for the same link, distributes them
across different compute nodes to maximize parallelism.
"""

from __future__ import annotations

from typing import Dict, Optional, List, Set
import numpy as np

from satlynk.task.dag import TaskDAG
from satlynk.network.contact_plan import ContactPlan, ContactWindow
from satlynk.scheduler.interface import (
    Scheduler, Schedule, TaskAssignment, EnvSnapshot, NodeSnapshot,
)


class LoadBalancedScheduler:
    """
    Bandwidth-aware scheduler that avoids piling tasks on the same link.
    
    Strategy:
        For each task, evaluate all reachable compute nodes.
        Score = transfer_time (considering current link load) + compute_time + return_time.
        Pick the node with minimum score.
        
    Key difference from Nearest-First/Shortest-Path:
        Tracks per-link task count and penalizes congested links.
    """

    def __init__(self, data_rate_bps: float = 2e6):
        self.data_rate_bps = data_rate_bps
        # Track how many active transfers are on each link (src, dst)
        self._link_load: Dict[tuple, int] = {}
        # Track node compute queue
        self._node_queue: Dict[int, float] = {}

    def on_task_arrive(self, task: TaskDAG, env: EnvSnapshot) -> Schedule:
        compute_nodes = [
            n for n in env.nodes.values()
            if n.role == "compute" and n.compute_flops > 0
        ]

        if not compute_nodes:
            return Schedule(assignments=[
                TaskAssignment(st.id, task.source_node, env.current_time_s)
                for st in task.subtasks
            ])

        source = task.source_node
        t_now = env.current_time_s
        input_size = getattr(task, 'input_size_bytes', 0)
        result_size = task.result_size_bytes
        dest = task.result_destination if task.result_destination >= 0 else source

        best_node = None
        best_completion = float('inf')

        for node in compute_nodes:
            nid = node.node_id
            
            # Check if link exists
            window = None
            for w in env.contact_plan.windows:
                if ((w.src == source and w.dst == nid) or
                    (w.dst == source and w.src == nid)):
                    if w.start_s <= t_now <= w.end_s:
                        window = w
                        break
            
            if window is None and source != nid:
                continue  # No active link

            # Effective rate considering contention
            link_key = (min(source, nid), max(source, nid))
            n_concurrent = self._link_load.get(link_key, 0) + 1
            effective_rate = self.data_rate_bps / n_concurrent

            # Transfer time with contention
            if source == nid:
                t_transfer_in = 0
            else:
                t_transfer_in = (input_size * 8) / effective_rate

            # Compute time (considering queue)
            t_compute = task.subtasks[0].compute_flops / node.compute_flops
            node_available = self._node_queue.get(nid, t_now)
            compute_start = max(t_now + t_transfer_in, node_available)
            t_compute_done = compute_start + t_compute

            # Return transfer
            if nid == dest:
                t_return = 0
            else:
                # Return link load
                ret_key = (min(nid, dest), max(nid, dest))
                ret_concurrent = self._link_load.get(ret_key, 0) + 1
                ret_rate = self.data_rate_bps / ret_concurrent
                t_return = (result_size * 8) / ret_rate

            t_completion = t_compute_done + t_return

            if t_completion < best_completion:
                best_completion = t_completion
                best_node = node

        if best_node is None:
            # Fallback to nearest
            source_pos = env.nodes[source].position
            best_node = min(compute_nodes,
                           key=lambda n: np.linalg.norm(n.position - source_pos))

        # Update tracking
        nid = best_node.node_id
        link_key = (min(source, nid), max(source, nid))
        self._link_load[link_key] = self._link_load.get(link_key, 0) + 1
        
        t_compute = task.subtasks[0].compute_flops / best_node.compute_flops
        input_transfer = (input_size * 8) / self.data_rate_bps if source != nid else 0
        self._node_queue[nid] = max(
            self._node_queue.get(nid, t_now),
            t_now + input_transfer
        ) + t_compute

        return Schedule(assignments=[
            TaskAssignment(st.id, best_node.node_id, env.current_time_s)
            for st in task.topological_order()
        ])

    def on_event(self, event_type, payload, env):
        return None
