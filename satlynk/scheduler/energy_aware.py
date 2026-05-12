"""Energy-Aware Scheduler — Skips low-battery nodes.

Extends Nearest-First by checking battery level before assignment.
Rejects nodes below a configurable threshold, preventing tasks from
failing due to SAFE_MODE transitions.
"""

from __future__ import annotations

from typing import Dict, Optional
import numpy as np

from satlynk.task.dag import TaskDAG
from satlynk.scheduler.interface import (
    Scheduler, Schedule, TaskAssignment, EnvSnapshot, NodeSnapshot,
)


class EnergyAwareScheduler:
    """
    Scheduler that avoids assigning to energy-depleted nodes.
    
    Strategy:
        1. Filter out nodes with battery < min_battery_pct
        2. Among remaining, pick nearest (like Nearest-First)
        3. If no node meets threshold, pick the one with highest battery
    """

    def __init__(self, min_battery_pct: float = 40.0):
        self.min_battery_pct = min_battery_pct

    def on_task_arrive(self, task: TaskDAG, env: EnvSnapshot) -> Schedule:
        source_pos = env.nodes[task.source_node].position

        compute_nodes = [
            n for n in env.nodes.values()
            if n.role == "compute" and n.compute_flops > 0
        ]

        if not compute_nodes:
            return Schedule(assignments=[
                TaskAssignment(st.id, task.source_node, env.current_time_s)
                for st in task.subtasks
            ])

        # Filter by energy
        healthy_nodes = [
            n for n in compute_nodes
            if n.battery_pct >= self.min_battery_pct
        ]

        if healthy_nodes:
            # Among healthy nodes, pick nearest
            target = min(
                healthy_nodes,
                key=lambda n: np.linalg.norm(n.position - source_pos)
            )
        else:
            # No healthy node — pick highest battery
            target = max(compute_nodes, key=lambda n: n.battery_pct)

        return Schedule(assignments=[
            TaskAssignment(st.id, target.node_id, env.current_time_s)
            for st in task.topological_order()
        ])

    def on_event(self, event_type, payload, env):
        return None
