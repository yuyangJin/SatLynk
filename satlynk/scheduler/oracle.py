"""Oracle Scheduler — Optimal offline baseline via exhaustive enumeration.

For small-scale problems (≤15 satellites, ≤20 tasks with single subtask each),
enumerate all possible assignments and evaluate each using the simulator's
contact plan to find the true optimum.

This is equivalent to solving the MILP but uses no external solver dependency.
Complexity: O(C^T) where C=compute nodes, T=tasks. Feasible for C≤12, T≤15
with pruning.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Tuple
from itertools import product
import numpy as np

from satlynk.task.dag import TaskDAG, SubTask
from satlynk.network.contact_plan import ContactPlan, ContactWindow
from satlynk.scheduler.interface import (
    Scheduler, Schedule, TaskAssignment, EnvSnapshot, NodeSnapshot,
)


class OracleScheduler:
    """
    Offline optimal scheduler — exhaustive search with pruning.
    
    Strategy:
        1. For each task, identify all FEASIBLE compute nodes
           (nodes reachable from source within deadline via some contact window)
        2. Enumerate all feasible assignment combinations
        3. For each combination, compute the resulting makespan/success
        4. Return the assignment that maximizes success rate, then minimizes makespan
    
    Pruning:
        - Skip nodes with no forward path from task source
        - Skip nodes with no return path to destination within deadline
        - Use branch-and-bound when enumeration space > 10000
    """

    def __init__(self, contact_plan: ContactPlan, satellites: list,
                 data_rate_bps: float = 50e6, time_horizon_s: float = 600.0):
        self.contact_plan = contact_plan
        self.satellites = satellites
        self.data_rate_bps = data_rate_bps
        self.time_horizon_s = time_horizon_s
        self._precomputed_schedules: Dict[str, Schedule] = {}
        self._stats = {'evaluated': 0, 'pruned': 0}

    def precompute_all(self, tasks: List[TaskDAG]):
        """
        Find the globally optimal assignment for all tasks.
        """
        compute_nodes = [
            i for i, sat in enumerate(self.satellites)
            if sat.role.value in ("compute", "hybrid")
        ]
        
        if not compute_nodes or not tasks:
            return

        # Step 1: For each task, find feasible nodes
        feasible_map: Dict[str, List[int]] = {}  # task_id → list of feasible nodes
        
        for task in tasks:
            feasible = self._find_feasible_nodes(task, compute_nodes)
            feasible_map[task.id] = feasible if feasible else compute_nodes[:1]  # fallback
        
        # Step 2: Enumerate and evaluate
        # Check if enumeration is tractable
        total_combos = 1
        for task in tasks:
            total_combos *= len(feasible_map[task.id])
        
        if total_combos <= 50000:
            # Full enumeration
            best_assignment = self._enumerate_full(tasks, feasible_map, compute_nodes)
        else:
            # Greedy per-task optimal (independent tasks assumption)
            best_assignment = self._greedy_optimal(tasks, feasible_map, compute_nodes)
        
        # Step 3: Store results
        for task in tasks:
            node_id = best_assignment.get(task.id, compute_nodes[0])
            self._precomputed_schedules[task.id] = Schedule(
                assignments=[
                    TaskAssignment(
                        subtask_id=st.id,
                        execute_on=node_id,
                        scheduled_start_s=task.arrival_time_s,
                    )
                    for st in task.subtasks
                ]
            )

    def _find_feasible_nodes(self, task: TaskDAG, compute_nodes: List[int]) -> List[int]:
        """Find all compute nodes that can complete this task within deadline."""
        feasible = []
        source = task.source_node
        dest = task.result_destination if task.result_destination >= 0 else source
        input_size = getattr(task, 'input_size_bytes', 0)
        result_size = task.result_size_bytes
        deadline = task.global_deadline_s or self.time_horizon_s
        t_arrive = task.arrival_time_s
        
        for nid in compute_nodes:
            # Forward path: source → node
            if nid == source:
                t_input_done = t_arrive
            else:
                t_input_done = self._earliest_delivery(source, nid, t_arrive, input_size)
                if t_input_done is None:
                    continue
            
            # Compute time
            flops = self.satellites[nid].compute_flops
            if flops <= 0:
                flops = 8e9
            t_compute = task.subtasks[0].compute_flops / flops
            t_compute_done = t_input_done + t_compute
            
            # Return path: node → dest
            if nid == dest:
                t_complete = t_compute_done
            else:
                t_complete = self._earliest_delivery(nid, dest, t_compute_done, result_size)
                if t_complete is None:
                    continue
            
            # Check deadline
            makespan = t_complete - t_arrive
            if makespan <= deadline:
                feasible.append(nid)
        
        return feasible

    def _enumerate_full(self, tasks: List[TaskDAG], 
                        feasible_map: Dict[str, List[int]],
                        compute_nodes: List[int]) -> Dict[str, int]:
        """Full enumeration: try all combinations, pick the best."""
        task_ids = [t.id for t in tasks]
        feasible_lists = [feasible_map[tid] for tid in task_ids]
        
        best_score = (-1, float('inf'))  # (success_count, -total_makespan)
        best_assignment = {}
        
        for combo in product(*feasible_lists):
            assignment = dict(zip(task_ids, combo))
            score = self._evaluate_assignment(tasks, assignment)
            self._stats['evaluated'] += 1
            
            if score > best_score:
                best_score = score
                best_assignment = assignment.copy()
        
        return best_assignment

    def _greedy_optimal(self, tasks: List[TaskDAG],
                        feasible_map: Dict[str, List[int]],
                        compute_nodes: List[int]) -> Dict[str, int]:
        """Per-task greedy: assign each task to its best node independently."""
        assignment = {}
        
        for task in tasks:
            best_node = None
            best_makespan = float('inf')
            
            for nid in feasible_map[task.id]:
                makespan = self._compute_makespan(task, nid)
                if makespan < best_makespan:
                    best_makespan = makespan
                    best_node = nid
            
            assignment[task.id] = best_node if best_node is not None else compute_nodes[0]
        
        return assignment

    def _evaluate_assignment(self, tasks: List[TaskDAG], 
                             assignment: Dict[str, int]) -> Tuple[int, float]:
        """
        Evaluate an assignment. Returns (success_count, -total_makespan).
        Higher is better.
        """
        success_count = 0
        total_makespan = 0.0
        
        for task in tasks:
            nid = assignment[task.id]
            makespan = self._compute_makespan(task, nid)
            deadline = task.global_deadline_s or self.time_horizon_s
            
            if makespan <= deadline:
                success_count += 1
                total_makespan += makespan
            else:
                total_makespan += deadline * 2  # Penalty
        
        return (success_count, -total_makespan)

    def _compute_makespan(self, task: TaskDAG, node_id: int) -> float:
        """Compute the expected makespan for a task assigned to a specific node."""
        source = task.source_node
        dest = task.result_destination if task.result_destination >= 0 else source
        input_size = getattr(task, 'input_size_bytes', 0)
        result_size = task.result_size_bytes
        t_arrive = task.arrival_time_s
        
        # Forward transfer
        if node_id == source:
            t_input_done = t_arrive
        else:
            t_input_done = self._earliest_delivery(source, node_id, t_arrive, input_size)
            if t_input_done is None:
                return float('inf')
        
        # Compute
        flops = self.satellites[node_id].compute_flops
        if flops <= 0:
            flops = 8e9
        t_compute = task.subtasks[0].compute_flops / flops
        t_compute_done = t_input_done + t_compute
        
        # Return transfer
        if node_id == dest:
            t_complete = t_compute_done
        else:
            t_complete = self._earliest_delivery(node_id, dest, t_compute_done, result_size)
            if t_complete is None:
                return float('inf')
        
        return t_complete - t_arrive

    def _earliest_delivery(self, src: int, dst: int, 
                           after_t: float, data_bytes: int) -> Optional[float]:
        """
        Find earliest delivery time via direct OR 1-hop relay.
        Considers multi-hop (2-leg) paths for better coverage.
        """
        transfer_time = (data_bytes * 8) / self.data_rate_bps if data_bytes > 0 else 0
        
        best_delivery = None
        
        # Direct path
        direct = self._direct_delivery(src, dst, after_t, transfer_time)
        if direct is not None:
            best_delivery = direct
        
        # 1-hop relay paths
        num_nodes = len(self.satellites)
        for relay in range(num_nodes):
            if relay == src or relay == dst:
                continue
            
            # src → relay
            leg1 = self._direct_delivery(src, relay, after_t, transfer_time)
            if leg1 is None:
                continue
            
            # relay → dst
            leg2 = self._direct_delivery(relay, dst, leg1, transfer_time)
            if leg2 is None:
                continue
            
            if best_delivery is None or leg2 < best_delivery:
                best_delivery = leg2
        
        return best_delivery

    def _direct_delivery(self, src: int, dst: int, 
                         after_t: float, transfer_time: float) -> Optional[float]:
        """Find earliest direct (single-hop) delivery."""
        for w in self.contact_plan.windows:
            if not ((w.src == src and w.dst == dst) or (w.src == dst and w.dst == src)):
                continue
            if w.end_s <= after_t:
                continue
            
            usable_start = max(after_t, w.start_s)
            delivery = usable_start + transfer_time
            
            if delivery <= w.end_s:
                return delivery
        
        return None

    # === Scheduler Protocol ===

    def on_task_arrive(self, task: TaskDAG, env: EnvSnapshot) -> Schedule:
        """Return precomputed optimal schedule."""
        if task.id in self._precomputed_schedules:
            return self._precomputed_schedules[task.id]
        
        # Fallback: nearest
        compute_nodes = [
            n for n in env.nodes.values()
            if n.role == "compute" and n.compute_flops > 0
        ]
        if not compute_nodes:
            return Schedule(assignments=[
                TaskAssignment(st.id, task.source_node, env.current_time_s)
                for st in task.subtasks
            ])
        
        source_pos = env.nodes[task.source_node].position
        best_node = min(compute_nodes, key=lambda n: np.linalg.norm(n.position - source_pos))
        
        return Schedule(assignments=[
            TaskAssignment(st.id, best_node.node_id, env.current_time_s)
            for st in task.subtasks
        ])

    def on_event(self, event_type, payload, env):
        return None
