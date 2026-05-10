"""Task DAG — Data structures for computational tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from enum import Enum


class TaskState(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    WAITING_DATA = "waiting_data"
    WAITING_WEIGHT = "waiting_weight"
    COMPUTING = "computing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class SubTask:
    """A single computational unit within a task DAG."""
    id: str
    compute_flops: float              # w_v: computation required
    required_model: Optional[str] = None  # Model weight needed (None = no model)
    model_size_bytes: int = 0         # m_v: model weight size
    output_size_bytes: int = 0        # Size of output data
    deadline_s: Optional[float] = None


@dataclass
class DataDependency:
    """An edge in the task DAG representing data flow."""
    src_task: str       # Producer subtask ID
    dst_task: str       # Consumer subtask ID
    data_size_bytes: int  # d_uv: data to transfer


@dataclass
class TaskDAG:
    """A directed acyclic graph of subtasks."""
    id: str
    source_node: int              # Originating satellite index
    arrival_time_s: float         # When the task was created
    subtasks: List[SubTask]
    dependencies: List[DataDependency]
    global_deadline_s: Optional[float] = None  # Max time to complete
    result_destination: int = -1  # Where to send final result (-1 = source)
    result_size_bytes: int = 0    # Final result size

    def __post_init__(self):
        self._subtask_map = {st.id: st for st in self.subtasks}
        self._predecessors: Dict[str, List[DataDependency]] = {}
        self._successors: Dict[str, List[DataDependency]] = {}
        for dep in self.dependencies:
            self._predecessors.setdefault(dep.dst_task, []).append(dep)
            self._successors.setdefault(dep.src_task, []).append(dep)

    def get_subtask(self, subtask_id: str) -> SubTask:
        return self._subtask_map[subtask_id]

    def get_predecessors(self, subtask_id: str) -> List[DataDependency]:
        return self._predecessors.get(subtask_id, [])

    def get_successors(self, subtask_id: str) -> List[DataDependency]:
        return self._successors.get(subtask_id, [])

    @property
    def entry_tasks(self) -> List[SubTask]:
        """Subtasks with no predecessors."""
        has_pred = {dep.dst_task for dep in self.dependencies}
        return [st for st in self.subtasks if st.id not in has_pred]

    @property
    def exit_tasks(self) -> List[SubTask]:
        """Subtasks with no successors."""
        has_succ = {dep.src_task for dep in self.dependencies}
        return [st for st in self.subtasks if st.id not in has_succ]

    def topological_order(self) -> List[SubTask]:
        """Return subtasks in topological order."""
        visited: Set[str] = set()
        order: List[SubTask] = []

        def dfs(st_id: str):
            if st_id in visited:
                return
            visited.add(st_id)
            for dep in self.get_predecessors(st_id):
                dfs(dep.src_task)
            order.append(self._subtask_map[st_id])

        for st in self.subtasks:
            dfs(st.id)

        return order
