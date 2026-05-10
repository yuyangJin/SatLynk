"""Metrics collector — Track simulation KPIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict
import numpy as np


@dataclass
class TaskResult:
    """Result for a single completed/failed task."""
    task_id: str
    arrival_time_s: float
    completion_time_s: float = -1.0
    success: bool = False
    makespan_s: float = 0.0
    relay_hops: int = 0
    energy_used_j: float = 0.0
    compute_node: int = -1
    return_via: List[int] = field(default_factory=list)


@dataclass
class SimMetrics:
    """Aggregated simulation metrics."""
    # Task performance
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    avg_makespan_s: float = 0.0
    max_makespan_s: float = 0.0
    success_rate: float = 0.0
    
    # Energy
    total_energy_j: float = 0.0
    energy_violations: int = 0
    min_battery_pct: float = 100.0
    
    # Network
    avg_relay_hops: float = 0.0
    total_data_transferred_bytes: int = 0
    
    # Timing
    sim_duration_s: float = 0.0
    wall_clock_s: float = 0.0
    events_processed: int = 0


class MetricsCollector:
    """Collect and aggregate simulation metrics."""
    
    def __init__(self):
        self.task_results: List[TaskResult] = []
        self.energy_samples: List[Dict[int, float]] = []  # periodic battery snapshots
        self.events_processed: int = 0
        self.data_transferred_bytes: int = 0
        self._transfer_log: List[Dict] = []
    
    def record_task_complete(self, result: TaskResult):
        self.task_results.append(result)
    
    def record_transfer(self, src: int, dst: int, size_bytes: int, time_s: float):
        self.data_transferred_bytes += size_bytes
        self._transfer_log.append({
            'src': src, 'dst': dst, 'bytes': size_bytes, 'time': time_s
        })
    
    def record_energy_snapshot(self, t: float, battery_pcts: Dict[int, float]):
        self.energy_samples.append({'time': t, **battery_pcts})
    
    def compute_metrics(self, sim_duration_s: float, wall_clock_s: float = 0.0) -> SimMetrics:
        m = SimMetrics()
        m.sim_duration_s = sim_duration_s
        m.wall_clock_s = wall_clock_s
        m.events_processed = self.events_processed
        m.total_data_transferred_bytes = self.data_transferred_bytes
        
        m.total_tasks = len(self.task_results)
        m.completed_tasks = sum(1 for r in self.task_results if r.success)
        m.failed_tasks = m.total_tasks - m.completed_tasks
        m.success_rate = m.completed_tasks / max(1, m.total_tasks)
        
        if m.completed_tasks > 0:
            makespans = [r.makespan_s for r in self.task_results if r.success]
            m.avg_makespan_s = np.mean(makespans)
            m.max_makespan_s = np.max(makespans)
            m.avg_relay_hops = np.mean([r.relay_hops for r in self.task_results if r.success])
        
        if self.energy_samples:
            all_pcts = []
            for sample in self.energy_samples:
                for k, v in sample.items():
                    if k != 'time':
                        all_pcts.append(v)
            if all_pcts:
                m.min_battery_pct = min(all_pcts)
        
        return m
