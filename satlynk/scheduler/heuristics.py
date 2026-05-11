"""Heuristic Schedulers — Comparison baselines beyond Nearest-First.

Implements:
    - RandomScheduler: Random assignment (lower bound reference)
    - ShortestPathScheduler: Assign to node with shortest-time path from source
    - CGR_EDF_Scheduler: Contact Graph Routing + Earliest Deadline First
"""

from __future__ import annotations

import random as py_random
from typing import Optional, List, Dict, Tuple
import numpy as np

from satlynk.task.dag import TaskDAG, SubTask
from satlynk.network.contact_plan import ContactPlan, ContactWindow
from satlynk.scheduler.interface import (
    Scheduler, Schedule, TaskAssignment, EnvSnapshot, NodeSnapshot,
)


class RandomScheduler:
    """
    Baseline 0: Assign each subtask to a random compute node.
    
    Lower bound reference — any real algorithm should beat this.
    Seed is configurable for reproducibility.
    """

    def __init__(self, seed: int = 42):
        self.rng = py_random.Random(seed)

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

        assignments = []
        for subtask in task.topological_order():
            node = self.rng.choice(compute_nodes)
            assignments.append(TaskAssignment(
                subtask_id=subtask.id,
                execute_on=node.node_id,
                scheduled_start_s=env.current_time_s,
            ))
        return Schedule(assignments=assignments)

    def on_event(self, event_type, payload, env):
        return None


class ShortestPathScheduler:
    """
    Baseline 2: Assign to the compute node reachable with minimum transfer time.
    
    Uses the contact plan to estimate actual transfer delay (accounts for
    when the next window opens), not just Euclidean distance.
    
    Strategy:
        For each candidate compute node, estimate:
            t_transfer = earliest time input can arrive at node
        Pick the node that minimizes (t_transfer + t_compute + t_return).
    """

    def __init__(self, data_rate_bps: float = 50e6):
        self.data_rate_bps = data_rate_bps

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

        # Evaluate each candidate
        best_node = None
        best_total = float('inf')

        for node in compute_nodes:
            nid = node.node_id
            
            # Transfer time: source → node
            if nid == source:
                t_input_arrive = t_now
            else:
                t_input_arrive = self._earliest_delivery(
                    env.contact_plan, source, nid, t_now, input_size
                )
                if t_input_arrive is None:
                    continue  # Unreachable

            # Compute time
            t_compute = task.subtasks[0].compute_flops / node.compute_flops if node.compute_flops > 0 else float('inf')
            t_compute_done = t_input_arrive + t_compute

            # Return time: node → dest
            if nid == dest:
                t_return_arrive = t_compute_done
            else:
                t_return_arrive = self._earliest_delivery(
                    env.contact_plan, nid, dest, t_compute_done, result_size
                )
                if t_return_arrive is None:
                    continue  # Can't return

            total_time = t_return_arrive - t_now
            if total_time < best_total:
                best_total = total_time
                best_node = node

        # Fallback to nearest if no path found
        if best_node is None:
            source_pos = env.nodes[source].position
            best_node = min(compute_nodes,
                           key=lambda n: np.linalg.norm(n.position - source_pos))

        return Schedule(assignments=[
            TaskAssignment(st.id, best_node.node_id, env.current_time_s)
            for st in task.topological_order()
        ])

    def _earliest_delivery(self, contact_plan: ContactPlan,
                           src: int, dst: int, after_t: float,
                           data_bytes: int) -> Optional[float]:
        """
        Find the earliest time data can be fully delivered from src to dst.
        Considers direct transfer only (no relay) for O(W) complexity.
        """
        transfer_time_s = (data_bytes * 8) / self.data_rate_bps if data_bytes > 0 else 0

        for w in contact_plan.windows:
            if not ((w.src == src and w.dst == dst) or (w.src == dst and w.dst == src)):
                continue
            if w.end_s <= after_t:
                continue
            
            usable_start = max(after_t, w.start_s)
            delivery_time = usable_start + transfer_time_s
            
            if delivery_time <= w.end_s:
                return delivery_time
        
        return None

    def on_event(self, event_type, payload, env):
        return None


class CGR_EDF_Scheduler:
    """
    Contact Graph Routing + Earliest Deadline First.
    
    CGR is the standard DTN (Delay-Tolerant Networking) routing algorithm
    used in space networks (RFC 9171). Combined with EDF priority:
    
    Strategy:
        1. Build a Contact Graph from the current contact plan
        2. For each task, find ALL feasible compute nodes via CGR
        3. Among feasible nodes, pick the one that gives earliest completion
        4. When multiple tasks compete, prioritize by earliest deadline
    
    Key difference from ShortestPath:
        - CGR considers MULTI-HOP routes (relay paths)
        - EDF prioritizes urgent tasks when resources are contested
    """

    def __init__(self, data_rate_bps: float = 50e6, max_hops: int = 3):
        self.data_rate_bps = data_rate_bps
        self.max_hops = max_hops
        self._node_load: Dict[int, float] = {}  # Track estimated node busy-until time

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

        # CGR: find best route for each candidate node
        best_node = None
        best_completion = float('inf')

        for node in compute_nodes:
            nid = node.node_id
            
            # Consider node load (EDF: don't pile onto busy nodes)
            node_available_at = self._node_load.get(nid, t_now)
            
            # Forward path: source → node (possibly multi-hop)
            if nid == source:
                t_input_arrive = t_now
            else:
                route_fwd = self._cgr_route(
                    env.contact_plan, source, nid, t_now,
                    input_size, env.nodes
                )
                if route_fwd is None:
                    continue
                t_input_arrive = route_fwd['delivery_time']

            # Must wait for both input AND node availability
            compute_start = max(t_input_arrive, node_available_at)
            
            # Compute time
            t_compute = task.subtasks[0].compute_flops / node.compute_flops if node.compute_flops > 0 else float('inf')
            t_compute_done = compute_start + t_compute

            # Return path: node → dest (possibly multi-hop)
            if nid == dest:
                t_completion = t_compute_done
            else:
                route_back = self._cgr_route(
                    env.contact_plan, nid, dest, t_compute_done,
                    result_size, env.nodes
                )
                if route_back is None:
                    continue
                t_completion = route_back['delivery_time']

            if t_completion < best_completion:
                best_completion = t_completion
                best_node = node

        # Fallback
        if best_node is None:
            source_pos = env.nodes[source].position
            best_node = min(compute_nodes,
                           key=lambda n: np.linalg.norm(n.position - source_pos))

        # Update load tracking
        nid = best_node.node_id
        t_compute = task.subtasks[0].compute_flops / best_node.compute_flops if best_node.compute_flops > 0 else 0
        self._node_load[nid] = max(self._node_load.get(nid, t_now), t_now) + t_compute

        return Schedule(assignments=[
            TaskAssignment(st.id, best_node.node_id, env.current_time_s)
            for st in task.topological_order()
        ])

    def _cgr_route(self, contact_plan: ContactPlan, src: int, dst: int,
                   after_t: float, data_bytes: int,
                   nodes: Dict[int, NodeSnapshot]) -> Optional[Dict]:
        """
        Contact Graph Routing: find earliest delivery via up to max_hops.
        
        Dijkstra-like on the contact graph where edge weights are
        (earliest delivery time at next hop).
        
        Returns: {'delivery_time': float, 'hops': int, 'path': [nodes]} or None
        """
        transfer_time_s = (data_bytes * 8) / self.data_rate_bps if data_bytes > 0 else 0

        # BFS/Dijkstra with time as "distance"
        # State: (delivery_time_at_node, node, hops, path)
        from heapq import heappush, heappop
        
        heap = [(after_t, 0, src, [src])]  # (time, hops, node, path)
        visited = {}  # node → best arrival time
        
        while heap:
            t_at_node, hops, current, path = heappop(heap)
            
            if current == dst:
                return {'delivery_time': t_at_node, 'hops': hops, 'path': path}
            
            if current in visited and visited[current] <= t_at_node:
                continue
            visited[current] = t_at_node
            
            if hops >= self.max_hops:
                continue
            
            # Explore all windows from current node
            for w in contact_plan.windows:
                # Find neighbor
                if w.src == current:
                    neighbor = w.dst
                elif w.dst == current:
                    neighbor = w.src
                else:
                    continue
                
                if neighbor in path:
                    continue  # No loops
                
                if w.end_s <= t_at_node:
                    continue  # Window already passed
                
                usable_start = max(t_at_node, w.start_s)
                delivery = usable_start + transfer_time_s
                
                if delivery > w.end_s:
                    continue  # Doesn't fit in window
                
                if neighbor not in visited or visited[neighbor] > delivery:
                    heappush(heap, (delivery, hops + 1, neighbor, path + [neighbor]))
        
        return None

    def on_event(self, event_type, payload, env):
        return None
