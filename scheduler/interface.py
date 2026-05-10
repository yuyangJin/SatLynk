"""Scheduler Interface — Protocol and base implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Dict, Any
import numpy as np

from oasis.task.dag import TaskDAG
from oasis.network.contact_plan import ContactPlan, ContactWindow


@dataclass
class TaskAssignment:
    """Assignment of a subtask to a node."""
    subtask_id: str
    execute_on: int        # Node index
    scheduled_start_s: float = 0.0


@dataclass
class Schedule:
    """Scheduler output: how to execute a task."""
    assignments: List[TaskAssignment]


@dataclass
class NodeSnapshot:
    """Snapshot of a single node's state (visible to scheduler)."""
    node_id: int
    role: str
    position: np.ndarray      # (3,) ECI position
    compute_flops: float
    compute_utilization: float = 0.0
    battery_pct: float = 100.0
    weight_cache: List[str] = field(default_factory=list)


@dataclass
class EnvSnapshot:
    """Complete environment state visible to the scheduler."""
    current_time_s: float
    nodes: Dict[int, NodeSnapshot]
    contact_plan: ContactPlan
    active_windows: List[ContactWindow]


class Scheduler(Protocol):
    """Scheduler interface — any scheduling algorithm must implement this."""

    def on_task_arrive(self, task: TaskDAG, env: EnvSnapshot) -> Schedule:
        """Called when a new task arrives. Must return assignment."""
        ...

    def on_event(self, event_type: str, payload: dict, env: EnvSnapshot) -> Optional[Schedule]:
        """Called on environment changes. Return new schedule or None."""
        ...


class NearestFirstScheduler:
    """Baseline 1: Assign each subtask to the nearest compute node."""

    def on_task_arrive(self, task: TaskDAG, env: EnvSnapshot) -> Schedule:
        source_pos = env.nodes[task.source_node].position
        
        # Find compute nodes
        compute_nodes = [
            n for n in env.nodes.values()
            if n.role == "compute" and n.compute_flops > 0
        ]
        
        if not compute_nodes:
            # Fallback: assign to source
            return Schedule(assignments=[
                TaskAssignment(st.id, task.source_node, env.current_time_s)
                for st in task.subtasks
            ])

        assignments = []
        for subtask in task.topological_order():
            # Find nearest compute node
            nearest = min(
                compute_nodes,
                key=lambda n: np.linalg.norm(n.position - source_pos)
            )
            assignments.append(TaskAssignment(
                subtask_id=subtask.id,
                execute_on=nearest.node_id,
                scheduled_start_s=env.current_time_s,
            ))

        return Schedule(assignments=assignments)

    def on_event(self, event_type, payload, env):
        return None
