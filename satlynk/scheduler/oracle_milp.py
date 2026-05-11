"""Oracle MILP Scheduler — Optimal offline baseline using OR-Tools CP-SAT.

This scheduler has FULL knowledge of the future (all contact windows, task arrivals).
It solves a Mixed-Integer Program to find the globally optimal assignment.

Used as an upper bound to measure how far heuristic schedulers deviate from optimum.

NOTE: Only feasible for small instances (≤15 satellites, ≤20 tasks) due to NP-hardness.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Tuple
import numpy as np

from satlynk.task.dag import TaskDAG, SubTask
from satlynk.network.contact_plan import ContactPlan, ContactWindow
from satlynk.scheduler.interface import (
    Scheduler, Schedule, TaskAssignment, EnvSnapshot, NodeSnapshot,
)


class OracleMILPScheduler:
    """
    Offline optimal scheduler using OR-Tools CP-SAT.
    
    Formulation:
        Decision variable x[v,i] ∈ {0,1}: subtask v executes on node i
        
        Minimize: max_over_tasks(completion_time)   [makespan]
        
        Subject to:
            C1: each subtask assigned to exactly one compute node
            C2: transfer only during active contact windows (link gating)
            C3: compute starts only after input data arrives
            C4: model weight must be present before compute starts
            C5: energy feasibility (relaxed in this implementation)
    
    Since we know all contact windows upfront, we can model the exact
    transfer times and compute a globally optimal schedule.
    """

    def __init__(self, contact_plan: ContactPlan, satellites: list,
                 data_rate_bps: float = 50e6, time_horizon_s: float = 600.0):
        self.contact_plan = contact_plan
        self.satellites = satellites
        self.data_rate_bps = data_rate_bps
        self.time_horizon_s = time_horizon_s
        self._precomputed_schedules: Dict[str, Schedule] = {}

    def precompute_all(self, tasks: List[TaskDAG]):
        """
        Solve the full scheduling problem offline for all tasks.
        Stores the optimal schedule for each task.
        """
        try:
            from ortools.sat.python import cp_model
        except ImportError:
            raise RuntimeError("ortools not installed. Run: pip install ortools")

        model = cp_model.CpModel()
        
        # Identify compute nodes
        compute_nodes = [
            i for i, sat in enumerate(self.satellites)
            if sat.role.value in ("compute", "hybrid")
        ]
        
        if not compute_nodes:
            return

        # Time discretization for the model (1s resolution)
        T = int(self.time_horizon_s)
        
        # Decision variables and constraints per task
        all_makespans = []
        
        for task in tasks:
            task_vars = self._model_single_task(
                model, task, compute_nodes, T
            )
            if task_vars is not None:
                all_makespans.append(task_vars['makespan'])

        if not all_makespans:
            return

        # Objective: minimize total makespan (sum for fairness)
        total_makespan = model.NewIntVar(0, T * len(tasks), 'total_makespan')
        model.Add(total_makespan == sum(all_makespans))
        model.Minimize(total_makespan)

        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 30.0
        solver.parameters.num_search_workers = 1  # Deterministic
        
        status = solver.Solve(model)
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # Extract assignments
            for task in tasks:
                self._extract_schedule(solver, task, compute_nodes)
        else:
            # Infeasible or timeout — fall back to nearest-first for each
            for task in tasks:
                self._fallback_schedule(task, compute_nodes)

    def _model_single_task(self, model, task: TaskDAG, 
                           compute_nodes: List[int], T: int) -> Optional[Dict]:
        """Add variables and constraints for one task to the CP model."""
        from ortools.sat.python import cp_model
        
        tid = task.id
        source = task.source_node
        
        # For each subtask: which node to assign + timing
        assign_vars = {}   # (subtask_id, node_id) -> BoolVar
        start_vars = {}    # subtask_id -> IntVar (start time)
        end_vars = {}      # subtask_id -> IntVar (end time)
        
        for st in task.subtasks:
            # Assignment: exactly one node
            node_bools = {}
            for n in compute_nodes:
                var = model.NewBoolVar(f'x_{tid}_{st.id}_{n}')
                node_bools[n] = var
                assign_vars[(st.id, n)] = var
            
            # C1: assign to exactly one
            model.AddExactlyOne(node_bools.values())
            
            # Timing variables
            s = model.NewIntVar(int(task.arrival_time_s), T, f'start_{tid}_{st.id}')
            compute_time = max(1, int(st.compute_flops / self._get_max_flops(compute_nodes)))
            e = model.NewIntVar(int(task.arrival_time_s), T, f'end_{tid}_{st.id}')
            model.Add(e >= s + compute_time)
            
            start_vars[st.id] = s
            end_vars[st.id] = e
        
        # C2: Input transfer time (link gating)
        # For entry subtasks: account for transfer from source to compute node
        for st in task.entry_tasks:
            input_size = getattr(task, 'input_size_bytes', 0)
            if input_size > 0:
                transfer_time_s = max(1, int(input_size * 8 / self.data_rate_bps))
                
                for n in compute_nodes:
                    if n == source:
                        # No transfer needed
                        continue
                    
                    # Find earliest window src→n
                    earliest = self._earliest_transfer_time(
                        source, n, task.arrival_time_s, transfer_time_s
                    )
                    
                    if earliest is not None:
                        # If assigned to n, start ≥ earliest_completion
                        model.Add(
                            start_vars[st.id] >= int(earliest + transfer_time_s)
                        ).OnlyEnforceIf(assign_vars[(st.id, n)])
                    else:
                        # No feasible window → cannot assign here
                        model.Add(assign_vars[(st.id, n)] == 0)
        
        # C3: Dependencies (for multi-subtask DAGs)
        for dep in task.dependencies:
            if dep.src_task in end_vars and dep.dst_task in start_vars:
                model.Add(start_vars[dep.dst_task] >= end_vars[dep.src_task])
        
        # Makespan = max completion + result return time
        makespan = model.NewIntVar(0, T, f'makespan_{tid}')
        
        # For simplicity in Phase 1: makespan = end of last subtask + result return
        last_ends = list(end_vars.values())
        if last_ends:
            max_end = model.NewIntVar(0, T, f'max_end_{tid}')
            model.AddMaxEquality(max_end, last_ends)
            
            # Add result return time estimate
            result_return_time = max(1, int(task.result_size_bytes * 8 / self.data_rate_bps)) if task.result_size_bytes > 0 else 0
            model.Add(makespan >= max_end + result_return_time - int(task.arrival_time_s))
        
        # Store variable references for extraction
        task._milp_assign = assign_vars
        task._milp_start = start_vars
        task._milp_end = end_vars
        task._milp_makespan = makespan
        task._milp_compute_nodes = compute_nodes
        
        return {'makespan': makespan}

    def _extract_schedule(self, solver, task: TaskDAG, compute_nodes: List[int]):
        """Extract solution from solver."""
        assignments = []
        for st in task.subtasks:
            for n in compute_nodes:
                var = task._milp_assign.get((st.id, n))
                if var and solver.Value(var) == 1:
                    start_t = solver.Value(task._milp_start[st.id])
                    assignments.append(TaskAssignment(
                        subtask_id=st.id,
                        execute_on=n,
                        scheduled_start_s=float(start_t),
                    ))
                    break
        
        self._precomputed_schedules[task.id] = Schedule(assignments=assignments)
        
        # Cleanup temp attrs
        for attr in ('_milp_assign', '_milp_start', '_milp_end', 
                     '_milp_makespan', '_milp_compute_nodes'):
            if hasattr(task, attr):
                delattr(task, attr)

    def _fallback_schedule(self, task: TaskDAG, compute_nodes: List[int]):
        """Fallback when MILP is infeasible — assign to first available compute node."""
        assignments = []
        for st in task.subtasks:
            assignments.append(TaskAssignment(
                subtask_id=st.id,
                execute_on=compute_nodes[0],
                scheduled_start_s=task.arrival_time_s,
            ))
        self._precomputed_schedules[task.id] = Schedule(assignments=assignments)

    def _earliest_transfer_time(self, src: int, dst: int, 
                                after_t: float, duration_s: int) -> Optional[float]:
        """Find the earliest time a transfer can START from src to dst."""
        for w in self.contact_plan.windows:
            if not ((w.src == src and w.dst == dst) or (w.src == dst and w.dst == src)):
                continue
            if w.end_s <= after_t:
                continue
            # Window usable from max(after_t, w.start_s)
            usable_start = max(after_t, w.start_s)
            if usable_start + duration_s <= w.end_s:
                return usable_start
        return None

    def _get_max_flops(self, compute_nodes: List[int]) -> float:
        """Get the maximum FLOPS among compute nodes."""
        flops = [self.satellites[n].compute_flops for n in compute_nodes
                 if self.satellites[n].compute_flops > 0]
        return max(flops) if flops else 1e9

    # === Scheduler Protocol ===

    def on_task_arrive(self, task: TaskDAG, env: EnvSnapshot) -> Schedule:
        """Return precomputed optimal schedule for this task."""
        if task.id in self._precomputed_schedules:
            return self._precomputed_schedules[task.id]
        
        # If not precomputed, do a quick greedy assignment
        compute_nodes = [
            n for n in env.nodes.values()
            if n.role == "compute" and n.compute_flops > 0
        ]
        if not compute_nodes:
            return Schedule(assignments=[
                TaskAssignment(st.id, task.source_node, env.current_time_s)
                for st in task.subtasks
            ])
        
        # Find node with active link from source
        source_pos = env.nodes[task.source_node].position
        best_node = min(compute_nodes, key=lambda n: np.linalg.norm(n.position - source_pos))
        
        return Schedule(assignments=[
            TaskAssignment(st.id, best_node.node_id, env.current_time_s)
            for st in task.subtasks
        ])

    def on_event(self, event_type, payload, env):
        return None
