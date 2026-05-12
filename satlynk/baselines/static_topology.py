"""
Baseline-A: 静态拓扑模拟器
=============================================================
代表 MEC offloading 论文的典型假设：
1. 链路永远可达（忽略 Contact Plan，任何星对随时可通信）
2. 带宽恒定（不建模争抢）
3. 不建模能耗

这是大量 satellite edge computing 论文使用的简化模型。
通过对比 SatLynk 结果，量化这些假设导致的乐观偏差。
"""

from __future__ import annotations

import time as walltime
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import numpy as np

from satlynk.orbital.constellation import (
    Satellite, Role, propagate_positions,
)
from satlynk.task.dag import TaskDAG, SubTask


@dataclass
class StaticSimConfig:
    """Static baseline configuration."""
    data_rate_bps: float = 2e6
    compute_flops_default: float = 1e12
    duration_s: float = 600.0


@dataclass
class StaticResult:
    """Result of a single task in static model."""
    task_id: str
    success: bool
    makespan_s: float
    assigned_node: int
    transfer_in_s: float
    compute_s: float
    transfer_out_s: float


@dataclass
class StaticMetrics:
    """Aggregate metrics from static baseline."""
    total_tasks: int = 0
    completed_tasks: int = 0
    success_rate: float = 0.0
    avg_makespan_s: float = 0.0
    max_makespan_s: float = 0.0
    task_results: List[StaticResult] = field(default_factory=list)
    wall_clock_s: float = 0.0


class StaticBaselineSimulator:
    """
    Static topology simulator — assumes ALL links always available.
    
    This represents what most MEC/offloading papers assume:
    - Any satellite can communicate with any other at any time
    - Fixed bandwidth (no contention modeling)
    - No energy constraints
    - Simple nearest-first assignment
    
    Purpose: show the gap between this idealized model and SatLynk's
    realistic Contact Plan + energy + contention modeling.
    """

    def __init__(self, config: StaticSimConfig):
        self.config = config
        self.satellites: List[Satellite] = []
        self.positions: Optional[np.ndarray] = None

    def set_satellites(self, satellites: List[Satellite]):
        self.satellites = satellites

    def precompute_positions(self, t: float = 0.0):
        """Compute positions at a single time point (static snapshot)."""
        times = np.array([t])
        self.positions = propagate_positions(self.satellites, times)[:, 0, :]

    def run_tasks(self, tasks: List[TaskDAG], strategy: str = "nearest") -> StaticMetrics:
        """
        Run all tasks with static topology assumption.
        
        Strategies:
            "nearest": assign to nearest compute node (classic MEC)
            "load_balanced": distribute across nodes (ideal)
        """
        start = walltime.time()
        
        compute_nodes = [
            (i, sat) for i, sat in enumerate(self.satellites)
            if sat.role == Role.COMPUTE
        ]

        if not compute_nodes:
            return StaticMetrics(total_tasks=len(tasks))

        results = []
        # Track load per node for load_balanced strategy
        node_busy_until: Dict[int, float] = {i: 0.0 for i, _ in compute_nodes}

        for task in tasks:
            source_idx = task.source_node
            source_pos = self.positions[source_idx]
            input_bytes = getattr(task, 'input_size_bytes', 0)
            result_bytes = task.result_size_bytes
            dest_idx = task.result_destination if task.result_destination >= 0 else source_idx

            if strategy == "nearest":
                # Always pick nearest (ignoring load, energy, link availability)
                target_idx = min(
                    compute_nodes,
                    key=lambda x: np.linalg.norm(self.positions[x[0]] - source_pos)
                )[0]
            elif strategy == "load_balanced":
                # Pick the node that finishes earliest (ideal load balancing)
                best_idx = None
                best_finish = float('inf')
                for idx, _ in compute_nodes:
                    t_in = (input_bytes * 8) / self.config.data_rate_bps if idx != source_idx else 0
                    t_comp = task.subtasks[0].compute_flops / self.satellites[idx].compute_flops
                    t_out = (result_bytes * 8) / self.config.data_rate_bps if idx != dest_idx else 0
                    start_time = max(task.arrival_time_s + t_in, node_busy_until[idx])
                    finish = start_time + t_comp + t_out
                    if finish < best_finish:
                        best_finish = finish
                        best_idx = idx
                target_idx = best_idx
            else:
                target_idx = compute_nodes[0][0]

            # Compute times (static model: all transfers succeed instantly at full rate)
            t_transfer_in = (input_bytes * 8) / self.config.data_rate_bps if target_idx != source_idx else 0
            t_compute = task.subtasks[0].compute_flops / self.satellites[target_idx].compute_flops
            t_transfer_out = (result_bytes * 8) / self.config.data_rate_bps if target_idx != dest_idx else 0

            # In static model: start = arrival + transfer_in, sequential on node
            effective_start = max(task.arrival_time_s + t_transfer_in, node_busy_until.get(target_idx, 0))
            makespan = (effective_start - task.arrival_time_s) + t_compute + t_transfer_out
            
            node_busy_until[target_idx] = effective_start + t_compute

            # Check deadline
            success = makespan <= task.global_deadline_s

            results.append(StaticResult(
                task_id=task.id,
                success=success,
                makespan_s=makespan,
                assigned_node=target_idx,
                transfer_in_s=t_transfer_in,
                compute_s=t_compute,
                transfer_out_s=t_transfer_out,
            ))

        elapsed = walltime.time() - start

        completed = [r for r in results if r.success]
        makespans = [r.makespan_s for r in completed] if completed else [0]

        return StaticMetrics(
            total_tasks=len(tasks),
            completed_tasks=len(completed),
            success_rate=len(completed) / len(tasks) if tasks else 0,
            avg_makespan_s=np.mean(makespans),
            max_makespan_s=max(makespans),
            task_results=results,
            wall_clock_s=elapsed,
        )
