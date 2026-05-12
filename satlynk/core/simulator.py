"""Simulator — The main integration class that wires all modules together.

Usage:
    sim = Simulator(config)
    sim.add_task(task_dag)           # or use a generator
    sim.set_scheduler(scheduler)
    results = sim.run()
"""

from __future__ import annotations

import time as walltime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Tuple
from enum import Enum
import numpy as np

from satlynk.core.engine import DESEngine, Event, EventType
from satlynk.orbital.constellation import (
    Satellite, Role, propagate_positions, compute_distances,
    check_line_of_sight, generate_walker_delta,
)
from satlynk.orbital.eclipse import compute_eclipse_schedule_vectorized
from satlynk.network.contact_plan import (
    ContactPlan, ContactWindow, compute_contact_plan,
)
from satlynk.task.dag import TaskDAG, SubTask, TaskState, DataDependency
from satlynk.task.weight_cache import WeightCacheManager, EvictionPolicy
from satlynk.scheduler.interface import (
    Scheduler, NearestFirstScheduler, Schedule, TaskAssignment,
    EnvSnapshot, NodeSnapshot,
)
from satlynk.energy.battery import (
    EnergyModel, PowerMode, PowerComponent, PowerProfile,
)
from satlynk.metrics.collector import MetricsCollector, TaskResult, SimMetrics
from satlynk.viz.exporter import VizRecorder


class TransferState(str, Enum):
    """State of a data transfer."""
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Transfer:
    """An in-flight data transfer."""
    id: str
    src_node: int
    dst_node: int
    size_bytes: int
    transferred_bytes: int = 0
    state: TransferState = TransferState.QUEUED
    task_id: str = ""
    subtask_id: str = ""  # which subtask triggered this
    purpose: str = ""     # "input" / "result" / "relay" / "weight"
    start_time: float = -1.0
    route: List[int] = field(default_factory=list)  # remaining hops after dst_node
    final_purpose: str = ""  # original purpose for last hop


@dataclass
class ComputeJob:
    """An active computation on a node."""
    subtask_id: str
    task_id: str
    node_id: int
    total_flops: float
    progress_flops: float = 0.0
    start_time: float = -1.0

    @property
    def remaining_flops(self) -> float:
        return self.total_flops - self.progress_flops

    def is_done(self) -> bool:
        return self.progress_flops >= self.total_flops


@dataclass
class SimConfig:
    """Simulation configuration."""
    duration_s: float = 60.0
    dt: float = 1.0
    max_skip_s: float = 60.0
    data_rate_bps: float = 10e6    # Default link rate
    compute_flops_default: float = 1e9  # Default compute node FLOPS
    idle_power_w: float = 2.0
    compute_power_w: float = 15.0
    comm_power_w: float = 5.0


class Simulator:
    """
    Main SatLynk simulator — integrates DES engine, orbital mechanics,
    contact plan, task management, scheduling, and energy.
    """

    def __init__(self, config: SimConfig):
        self.config = config
        self.engine = DESEngine(
            duration_s=config.duration_s,
            dt=config.dt,
            max_skip_s=config.max_skip_s,
        )
        self.energy = EnergyModel(0)
        self.metrics = MetricsCollector()
        self.scheduler: Scheduler = NearestFirstScheduler()

        # State
        self.satellites: List[Satellite] = []
        self.contact_plan: Optional[ContactPlan] = None
        self.positions: Optional[np.ndarray] = None  # (N, T, 3)
        self.times: Optional[np.ndarray] = None

        # Runtime state
        self._tasks: Dict[str, TaskDAG] = {}
        self._subtask_states: Dict[str, TaskState] = {}
        self._subtask_assignments: Dict[str, int] = {}  # subtask_id → node_id
        self._active_transfers: Dict[str, Transfer] = {}
        self._active_computes: Dict[str, ComputeJob] = {}
        self._pending_tasks: List[TaskDAG] = []
        self._completed_data: Dict[str, Dict[str, int]] = {}  # subtask → {dep: bytes_received}
        self._task_results: Dict[str, TaskResult] = {}

        # Viz recording
        self.viz: Optional[VizRecorder] = None
        
        # Phase 2: Weight cache + Eclipse
        self.weight_mgr = WeightCacheManager()
        self.eclipse_map: Optional[np.ndarray] = None  # (N, T) boolean

        # Register engine callbacks
        self.engine.register_step_callback(self._step_transfers)
        self.engine.register_step_callback(self._step_computes)
        self.engine.register_step_callback(self._step_energy)
        self.engine.set_idle_checker(self._is_idle)

        # Register event handlers
        self.engine.register_handler(EventType.TASK_ARRIVE, self._on_task_arrive)
        self.engine.register_handler(EventType.LINK_UP, self._on_link_up)
        self.engine.register_handler(EventType.LINK_DOWN, self._on_link_down)
        self.engine.register_handler(EventType.TRANSFER_DONE, self._on_transfer_done)
        self.engine.register_handler(EventType.COMPUTE_DONE, self._on_compute_done)
        self.engine.register_handler(EventType.ECLIPSE_ENTER, self._on_eclipse_enter)
        self.engine.register_handler(EventType.ECLIPSE_EXIT, self._on_eclipse_exit)

    def enable_viz_recording(self, position_interval_s: float = 1.0,
                             energy_interval_s: float = 1.0) -> VizRecorder:
        """Enable visualization recording. Call after set_satellites/set_contact_plan."""
        self.viz = VizRecorder(
            position_sample_interval_s=position_interval_s,
            energy_sample_interval_s=energy_interval_s,
        )
        self.viz.init_from_simulator(self)
        # Insert viz sampling into step callbacks
        self.engine.register_step_callback(self._step_viz)
        return self.viz

    # === Setup ===

    def set_satellites(self, satellites: List[Satellite]):
        """Set the satellite constellation."""
        self.satellites = satellites
        self.energy = EnergyModel(len(satellites))
        for i, sat in enumerate(satellites):
            if sat.role in (Role.COMPUTE, Role.HYBRID):
                # Compute satellite power profile
                profile = PowerProfile(
                    base_w=self.config.idle_power_w,
                    detector_w=0.0,
                    comm_tx_w=self.config.comm_power_w,
                    comm_rx_w=self.config.comm_power_w * 0.4,
                    compute_w=self.config.compute_power_w,
                    heater_w=1.0,
                )
                self.energy.init_node(i, sat.power_solar_w, sat.battery_capacity_wh,
                                      power_profile=profile)
                # Init weight cache (use 75% storage for weights)
                cache_bytes = int(sat.storage_bytes * 0.75) if sat.storage_bytes > 0 else int(48e9)
                self.weight_mgr.init_node(i, cache_bytes)
            elif sat.role == Role.DETECTOR:
                # Detector satellite power profile
                profile = PowerProfile(
                    base_w=self.config.idle_power_w * 0.5,
                    detector_w=3.0,  # Sensor payload always on
                    comm_tx_w=self.config.comm_power_w,
                    comm_rx_w=self.config.comm_power_w * 0.4,
                    compute_w=self.config.compute_power_w,
                    heater_w=0.5,
                )
                self.energy.init_node(i, sat.power_solar_w, sat.battery_capacity_wh,
                                      power_profile=profile)
                # Detector payload is always active
                self.energy.activate_component(i, "payload_sensor", PowerComponent.DETECTOR)

    def set_contact_plan(self, plan: ContactPlan):
        """Set a precomputed contact plan (or use compute_contact_plan)."""
        self.contact_plan = plan
        self._preload_link_events(plan)

    def set_scheduler(self, scheduler: Scheduler):
        """Set the scheduling algorithm."""
        self.scheduler = scheduler

    def add_task(self, task: TaskDAG):
        """Add a task to be injected at its arrival_time."""
        self.engine.schedule(Event(
            time=task.arrival_time_s,
            type=EventType.TASK_ARRIVE,
            payload={'task_id': task.id},
        ))
        self._tasks[task.id] = task

    def precompute_orbits(self):
        """Precompute positions, contact plan, and eclipse schedule."""
        self.times = np.arange(0, self.config.duration_s + self.config.dt, self.config.dt)
        self.positions = propagate_positions(self.satellites, self.times)

        # Compute contact plan
        self.contact_plan = compute_contact_plan(
            self.satellites, self.times, self.positions,
            data_rate_bps=self.config.data_rate_bps,
        )
        self._preload_link_events(self.contact_plan)
        
        # Compute eclipse schedule
        self.eclipse_map, eclipse_windows = compute_eclipse_schedule_vectorized(
            self.positions, self.times
        )
        # Preload eclipse events
        events = []
        for i, windows in enumerate(eclipse_windows):
            for (enter_t, exit_t) in windows:
                events.append(Event(time=enter_t, type=EventType.ECLIPSE_ENTER,
                                    payload={'node': i}))
                events.append(Event(time=exit_t, type=EventType.ECLIPSE_EXIT,
                                    payload={'node': i}))
        if events:
            self.engine.schedule_batch(events)

    # === Run ===

    def run(self) -> SimMetrics:
        """Run the full simulation and return metrics."""
        t_start = walltime.time()
        self.engine.run()
        t_end = walltime.time()

        self.metrics.events_processed = self.engine.events_processed
        return self.metrics.compute_metrics(
            sim_duration_s=self.config.duration_s,
            wall_clock_s=t_end - t_start,
        )

    # === Internal: Preloading ===

    def _preload_link_events(self, plan: ContactPlan):
        """Batch-insert LINK_UP/LINK_DOWN events from contact plan."""
        events = []
        for w in plan.windows:
            events.append(Event(
                time=w.start_s, type=EventType.LINK_UP,
                payload={'src': w.src, 'dst': w.dst, 'window': w},
            ))
            events.append(Event(
                time=w.end_s, type=EventType.LINK_DOWN,
                payload={'src': w.src, 'dst': w.dst},
            ))
        self.engine.schedule_batch(events)

    # === Internal: Step Callbacks ===

    def _step_transfers(self, t: float, dt: float):
        """Advance all active transfers — with bandwidth sharing."""
        completed = []
        
        # Group in-progress transfers by link for bandwidth sharing
        link_transfers: Dict[Tuple[int,int], List[str]] = {}
        for tid, transfer in self._active_transfers.items():
            if transfer.state != TransferState.IN_PROGRESS:
                continue
            key = (min(transfer.src_node, transfer.dst_node), max(transfer.src_node, transfer.dst_node))
            link_transfers.setdefault(key, []).append(tid)
        
        for link_key, tids in link_transfers.items():
            # Get link rate
            src, dst = link_key
            window = self.contact_plan.get_window(src, dst, t)
            if window is None:
                # Link down — stall all transfers on this link
                for tid in tids:
                    self._active_transfers[tid].state = TransferState.QUEUED
                continue
            
            # Fair share: divide bandwidth equally among concurrent transfers
            rate_bps = window.avg_rate_bps
            per_transfer_rate = rate_bps / len(tids)
            bytes_per_transfer = int(per_transfer_rate * dt / 8)
            
            for tid in tids:
                transfer = self._active_transfers[tid]
                transfer.transferred_bytes += bytes_per_transfer
                if transfer.transferred_bytes >= transfer.size_bytes:
                    transfer.transferred_bytes = transfer.size_bytes
                    transfer.state = TransferState.DONE
                    completed.append(tid)
                    self.engine.schedule(Event(
                        time=t + dt * 0.5,
                        type=EventType.TRANSFER_DONE,
                        payload={'transfer_id': tid},
                    ))

    def _step_computes(self, t: float, dt: float):
        """Advance all active computations by dt."""
        completed = []
        for cid, job in self._active_computes.items():
            if not self.energy.can_compute(job.node_id):
                continue  # Node in low-power mode

            # Get node compute rate
            sat = self.satellites[job.node_id]
            flops_per_s = sat.compute_flops if sat.compute_flops > 0 else self.config.compute_flops_default
            job.progress_flops += flops_per_s * dt

            if job.is_done():
                completed.append(cid)
                self.engine.schedule(Event(
                    time=t + dt * 0.5,
                    type=EventType.COMPUTE_DONE,
                    payload={'job_id': cid, 'subtask_id': job.subtask_id, 'task_id': job.task_id},
                ))

        # Remove completed
        for cid in completed:
            job = self._active_computes.pop(cid)
            # Deactivate compute power component
            self.energy.deactivate_component(job.node_id, f"compute_{cid}")

    def _step_energy(self, t: float, dt: float):
        """Update energy model."""
        events = self.energy.step(t, dt)
        # Record periodic snapshots
        if int(t) % 10 == 0:
            pcts = {i: self.energy.get_battery_pct(i) for i in range(len(self.satellites))}
            self.metrics.record_energy_snapshot(t, pcts)
        
        # Check task deadlines
        for task_id, task in self._tasks.items():
            result = self._task_results.get(task_id)
            if result and not result.success and result.completion_time_s < 0:
                if task.global_deadline_s and (t - task.arrival_time_s) > task.global_deadline_s:
                    result.success = False
                    result.completion_time_s = t
                    result.makespan_s = t - task.arrival_time_s
                    self.metrics.record_task_complete(result)
                    # Clean up active transfers for this task
                    to_remove = [tid for tid, xfer in self._active_transfers.items() 
                                 if xfer.task_id == task_id]
                    for tid in to_remove:
                        del self._active_transfers[tid]

    def _step_viz(self, t: float, dt: float):
        """Sample data for visualization."""
        if self.viz:
            self.viz.sample_positions(t, self)
            self.viz.sample_energy(t, self)

    def _is_idle(self) -> bool:
        """Check if simulation is idle (enables time-skip)."""
        return (
            len(self._active_transfers) == 0
            and len(self._active_computes) == 0
            and len(self._pending_tasks) == 0
        )

    # === Internal: Event Handlers ===

    def _on_task_arrive(self, event: Event):
        """Handle new task arrival."""
        task_id = event.payload['task_id']
        task = self._tasks[task_id]
        t = event.time

        # Viz: record event
        if self.viz:
            self.viz.record_event(t, "task_arrive",
                                  f"{task_id} from node {task.source_node}",
                                  node=task.source_node)

        # Initialize task state
        for st in task.subtasks:
            self._subtask_states[st.id] = TaskState.PENDING
            self._completed_data[st.id] = {}

        # Create result tracker
        self._task_results[task_id] = TaskResult(
            task_id=task_id,
            arrival_time_s=t,
        )

        # Call scheduler
        env = self._make_env_snapshot(t)
        schedule = self.scheduler.on_task_arrive(task, env)

        # Apply schedule
        self._apply_schedule(task, schedule, t)

    def _on_link_up(self, event: Event):
        """Link became available — check if any queued transfers can start."""
        src = event.payload['src']
        dst = event.payload['dst']
        for tid, transfer in self._active_transfers.items():
            if transfer.state == TransferState.QUEUED:
                if (transfer.src_node == src and transfer.dst_node == dst) or \
                   (transfer.src_node == dst and transfer.dst_node == src):
                    transfer.state = TransferState.IN_PROGRESS
                    transfer.start_time = event.time
                    # Activate comm power components
                    self.energy.activate_component(
                        transfer.src_node, f"tx_{tid}", PowerComponent.COMM_TX)
                    self.energy.activate_component(
                        transfer.dst_node, f"rx_{tid}", PowerComponent.COMM_RX)

    def _on_link_down(self, event: Event):
        """Link went down — stall any transfers on this link."""
        src = event.payload['src']
        dst = event.payload['dst']
        for tid, transfer in list(self._active_transfers.items()):
            if transfer.state == TransferState.IN_PROGRESS:
                if (transfer.src_node == src and transfer.dst_node == dst) or \
                   (transfer.src_node == dst and transfer.dst_node == src):
                    transfer.state = TransferState.QUEUED
                    # Deactivate comm power while stalled
                    self.energy.deactivate_component(transfer.src_node, f"tx_{tid}")
                    self.energy.deactivate_component(transfer.dst_node, f"rx_{tid}")

    def _on_transfer_done(self, event: Event):
        """A data transfer completed."""
        tid = event.payload['transfer_id']
        transfer = self._active_transfers.pop(tid, None)
        if transfer is None:
            return

        t = event.time
        self.metrics.record_transfer(transfer.src_node, transfer.dst_node,
                                     transfer.size_bytes, t)

        # Deactivate comm power components
        self.energy.deactivate_component(transfer.src_node, f"tx_{tid}")
        self.energy.deactivate_component(transfer.dst_node, f"rx_{tid}")

        # Viz: record transfer end
        if self.viz:
            self.viz.record_transfer_end(t, transfer.src_node, transfer.dst_node, transfer.purpose)
            self.viz.record_event(t, "transfer_done",
                                  f"{transfer.purpose}: {transfer.src_node}→{transfer.dst_node} "
                                  f"({transfer.size_bytes/1e6:.2f}MB)",
                                  node=transfer.dst_node)

        if transfer.purpose == "input":
            # Input data arrived at compute node — check if subtask can start
            self._try_start_compute(transfer.subtask_id, transfer.task_id, t)

        elif transfer.purpose == "relay_fwd":
            # Intermediate hop completed — forward to next node in route
            remaining = transfer.route
            if remaining:
                next_dst = remaining[0]
                new_route = remaining[1:]
                self._start_transfer(
                    src=transfer.dst_node,
                    dst=next_dst,
                    size_bytes=transfer.size_bytes,
                    task_id=transfer.task_id,
                    subtask_id=transfer.subtask_id,
                    purpose=transfer.final_purpose if not new_route else "relay_fwd",
                    t=t,
                    route=new_route,
                    final_purpose=transfer.final_purpose,
                )
            else:
                # No more hops, treat as final purpose
                if transfer.final_purpose == "input":
                    self._try_start_compute(transfer.subtask_id, transfer.task_id, t)
                elif transfer.final_purpose in ("result_direct", "result"):
                    self._complete_task(transfer.task_id, t)

        elif transfer.purpose == "weight":
            # Model weight arrived — cache it and retry compute
            task = self._tasks[transfer.task_id]
            subtask = task.get_subtask(transfer.subtask_id)
            if subtask.required_model:
                self.weight_mgr.cache_weight(transfer.dst_node, subtask.required_model, t)
            self._try_start_compute(transfer.subtask_id, transfer.task_id, t)

        elif transfer.purpose == "result_direct":
            # Result arrived at destination — task complete!
            self._complete_task(transfer.task_id, t)

        elif transfer.purpose == "relay":
            # Result arrived at relay node — need to forward to destination
            task = self._tasks[transfer.task_id]
            dest = task.result_destination if task.result_destination >= 0 else task.source_node
            self._start_transfer(
                src=transfer.dst_node,
                dst=dest,
                size_bytes=transfer.size_bytes,
                task_id=transfer.task_id,
                subtask_id=transfer.subtask_id,
                purpose="result_direct",
                t=t,
            )

    def _on_compute_done(self, event: Event):
        """A computation finished."""
        subtask_id = event.payload['subtask_id']
        task_id = event.payload['task_id']
        t = event.time

        self._subtask_states[subtask_id] = TaskState.DONE
        task = self._tasks[task_id]

        # Viz: record compute end
        if self.viz:
            compute_node = self._subtask_assignments[subtask_id]
            self.viz.record_compute_end(t, compute_node, subtask_id)
            self.viz.record_event(t, "compute_done",
                                  f"{subtask_id}@node{compute_node} done",
                                  node=compute_node)

        # Check if all subtasks done
        all_done = all(
            self._subtask_states.get(st.id) == TaskState.DONE
            for st in task.subtasks
        )

        if all_done:
            # All computation done — return result
            compute_node = self._subtask_assignments[subtask_id]
            dest = task.result_destination if task.result_destination >= 0 else task.source_node

            if compute_node == dest:
                # Result already at destination
                self._complete_task(task_id, t)
            else:
                # Need to transfer result back — try relay route (active now)
                route = self._find_relay_route(compute_node, dest, t)
                if route:
                    first_hop = route[0]
                    remaining = route[1:] + [dest]
                    self._start_transfer(
                        src=compute_node, dst=first_hop,
                        size_bytes=task.result_size_bytes,
                        task_id=task_id, subtask_id=subtask_id,
                        purpose="relay_fwd", t=t,
                        route=remaining,
                        final_purpose="result_direct",
                    )
                else:
                    # No fully-active relay route — try old relay logic (1-hop with future window)
                    relay_node = self._find_relay(compute_node, dest, t)
                    if relay_node is not None:
                        self._start_transfer(
                            src=compute_node, dst=relay_node,
                            size_bytes=task.result_size_bytes,
                            task_id=task_id, subtask_id=subtask_id,
                            purpose="relay", t=t,
                        )
                    else:
                        # Direct transfer (will queue if link not active)
                        self._start_transfer(
                            src=compute_node, dst=dest,
                            size_bytes=task.result_size_bytes,
                            task_id=task_id, subtask_id=subtask_id,
                            purpose="result_direct", t=t,
                        )

    # === Internal: Actions ===

    def _apply_schedule(self, task: TaskDAG, schedule: Schedule, t: float):
        """Apply a scheduling decision."""
        for assignment in schedule.assignments:
            st_id = assignment.subtask_id
            node_id = assignment.execute_on
            self._subtask_assignments[st_id] = node_id
            self._subtask_states[st_id] = TaskState.SCHEDULED

            # Check if this subtask needs input data transferred
            subtask = task.get_subtask(st_id)
            predecessors = task.get_predecessors(st_id)

            if not predecessors and task.source_node != node_id:
                # Entry task — need to send input from source to compute node
                input_size = getattr(task, 'input_size_bytes', 0)
                if input_size > 0:
                    # Check if direct link exists; if not, find relay path
                    route = self._find_relay_route(task.source_node, node_id, t)
                    if route:
                        # Multi-hop: src → route[0] → route[1] → ... → dst
                        first_hop = route[0]
                        remaining = route[1:] + [node_id]
                        self._start_transfer(
                            src=task.source_node, dst=first_hop,
                            size_bytes=input_size,
                            task_id=task.id, subtask_id=st_id,
                            purpose="relay_fwd", t=t,
                            route=remaining,
                            final_purpose="input",
                        )
                    else:
                        self._start_transfer(
                            src=task.source_node, dst=node_id,
                            size_bytes=input_size,
                            task_id=task.id, subtask_id=st_id,
                            purpose="input", t=t,
                        )
                else:
                    self._try_start_compute(st_id, task.id, t)
            elif not predecessors and task.source_node == node_id:
                # Entry task on source node — start immediately
                self._try_start_compute(st_id, task.id, t)
            # Tasks with predecessors will be triggered by _on_compute_done

    def _start_transfer(self, src: int, dst: int, size_bytes: int,
                        task_id: str, subtask_id: str, purpose: str, t: float,
                        route: List[int] = None, final_purpose: str = ""):
        """Initiate a data transfer, optionally via multi-hop route.
        
        If route is provided, the transfer goes src → dst → route[0] → route[1] → ...
        Each hop is a separate transfer; on completion of each hop, the next is started.
        """
        # If route provided and dst is not the final destination, mark as relay hop
        if route and len(route) > 0:
            actual_purpose = "relay_fwd"
            remaining_route = route
        else:
            actual_purpose = purpose
            remaining_route = []

        tid = f"xfer_{task_id}_{subtask_id}_{actual_purpose}_{t:.1f}_{src}_{dst}"
        transfer = Transfer(
            id=tid, src_node=src, dst_node=dst,
            size_bytes=size_bytes,
            task_id=task_id, subtask_id=subtask_id,
            purpose=actual_purpose,
            route=remaining_route,
            final_purpose=final_purpose or purpose,
        )

        # Check if link is currently available
        window = self.contact_plan.get_window(src, dst, t)
        if window and window.is_active(t):
            transfer.state = TransferState.IN_PROGRESS
            transfer.start_time = t
            # Activate comm power components
            self.energy.activate_component(src, f"tx_{tid}", PowerComponent.COMM_TX)
            self.energy.activate_component(dst, f"rx_{tid}", PowerComponent.COMM_RX)
        else:
            transfer.state = TransferState.QUEUED

        self._active_transfers[tid] = transfer

        # Viz: record transfer start
        if self.viz:
            self.viz.record_transfer_start(t, src, dst, size_bytes, purpose, task_id)
            self.viz.record_event(t, "transfer_start",
                                  f"{purpose}: {src}→{dst} ({size_bytes/1e6:.2f}MB)",
                                  node=src)

    def _try_start_compute(self, subtask_id: str, task_id: str, t: float):
        """Try to start computing a subtask (if all inputs ready + weight cached)."""
        node_id = self._subtask_assignments.get(subtask_id)
        if node_id is None:
            return

        task = self._tasks[task_id]
        subtask = task.get_subtask(subtask_id)

        # Check energy
        if not self.energy.can_compute(node_id):
            return

        # C4: Check weight cache
        if subtask.required_model:
            if not self.weight_mgr.has_weight(node_id, subtask.required_model):
                # Need to fetch weight — find source and start transfer
                self._subtask_states[subtask_id] = TaskState.WAITING_WEIGHT
                source = self.weight_mgr.find_nearest_source(subtask.required_model, exclude_node=node_id)
                if source is not None:
                    self._start_transfer(
                        src=source, dst=node_id,
                        size_bytes=subtask.model_size_bytes,
                        task_id=task_id, subtask_id=subtask_id,
                        purpose="weight", t=t,
                    )
                # else: weight unavailable in constellation — task will stall
                return
            else:
                # Weight available — mark as used
                self.weight_mgr.use_weight(node_id, subtask.required_model, t)

        # Start computation
        self._subtask_states[subtask_id] = TaskState.COMPUTING
        job_id = f"comp_{task_id}_{subtask_id}"
        job = ComputeJob(
            subtask_id=subtask_id,
            task_id=task_id,
            node_id=node_id,
            total_flops=subtask.compute_flops,
            start_time=t,
        )
        self._active_computes[job_id] = job
        # Activate compute power component
        self.energy.activate_component(node_id, f"compute_{job_id}", PowerComponent.COMPUTE)

        # Viz: record compute start
        if self.viz:
            self.viz.record_compute_start(t, node_id, task_id, subtask_id, subtask.compute_flops)
            self.viz.record_event(t, "compute_start",
                                  f"{subtask_id}@node{node_id} ({subtask.compute_flops/1e9:.0f}GFLOP)",
                                  node=node_id)

    def _find_relay(self, src: int, dst: int, t: float) -> Optional[int]:
        """Find an intermediate relay node reachable from src that can later reach dst."""
        for i in range(len(self.satellites)):
            if i == src or i == dst:
                continue
            # Can src reach i now?
            w_si = self.contact_plan.get_window(src, i, t)
            if w_si and w_si.is_active(t):
                # Can i reach dst later?
                future = self.contact_plan.get_future(i, t, self.config.duration_s - t)
                for fw in future:
                    other = fw.dst if fw.src == i else fw.src
                    if other == dst:
                        return i
        return None

    def _on_eclipse_enter(self, event: Event):
        """Satellite enters Earth's shadow — no solar charging."""
        node = event.payload['node']
        self.energy.set_eclipsed(node, True)
        if self.viz:
            self.viz.record_event(event.time, "eclipse_enter", 
                                  f"node{node} enters shadow", node=node)

    def _on_eclipse_exit(self, event: Event):
        """Satellite exits shadow — solar charging resumes."""
        node = event.payload['node']
        self.energy.set_eclipsed(node, False)
        if self.viz:
            self.viz.record_event(event.time, "eclipse_exit",
                                  f"node{node} exits shadow", node=node)

    def _complete_task(self, task_id: str, t: float):
        """Mark a task as completed."""
        result = self._task_results[task_id]
        result.completion_time_s = t
        result.success = True
        result.makespan_s = t - result.arrival_time_s

        # Count relay hops
        task = self._tasks[task_id]
        result_transfers = [
            xfer for xfer in self.metrics._transfer_log
            if xfer.get('task_id') == task_id
        ]
        result.relay_hops = max(0, len(result_transfers) - 1)

        self.metrics.record_task_complete(result)

        # Viz: record task complete
        if self.viz:
            self.viz.record_event(t, "task_complete",
                                  f"{task_id} done (makespan={result.makespan_s:.1f}s)",
                                  node=task.source_node)

    def _find_relay_route(self, src: int, dst: int, t: float) -> List[int]:
        """Find a relay path from src to dst if no direct link exists.
        
        Returns list of intermediate nodes (excluding src and dst), or empty list
        if direct link exists or no relay path found.
        """
        # Check direct link first
        direct = self.contact_plan.get_window(src, dst, t)
        if direct and direct.is_active(t):
            return []  # Direct link works, no relay needed
        
        # BFS for 1-hop relay: src → relay → dst
        for w1 in self.contact_plan.windows:
            if not (w1.start_s <= t <= w1.end_s):
                continue
            # Find links from src
            if w1.src == src:
                relay = w1.dst
            elif w1.dst == src:
                relay = w1.src
            else:
                continue
            
            if relay == dst:
                return []  # Actually direct
            
            # Check relay → dst
            w2 = self.contact_plan.get_window(relay, dst, t)
            if w2 and w2.is_active(t):
                return [relay]
        
        # 2-hop relay: src → r1 → r2 → dst
        for w1 in self.contact_plan.windows:
            if not (w1.start_s <= t <= w1.end_s):
                continue
            if w1.src == src:
                r1 = w1.dst
            elif w1.dst == src:
                r1 = w1.src
            else:
                continue
            if r1 == dst:
                continue
            
            for w2 in self.contact_plan.windows:
                if not (w2.start_s <= t <= w2.end_s):
                    continue
                if w2.src == r1:
                    r2 = w2.dst
                elif w2.dst == r1:
                    r2 = w2.src
                else:
                    continue
                if r2 == src or r2 == r1:
                    continue
                if r2 == dst:
                    return [r1]  # Actually 1-hop through r1
                
                w3 = self.contact_plan.get_window(r2, dst, t)
                if w3 and w3.is_active(t):
                    return [r1, r2]
        
        return []  # No relay path found

    def _make_env_snapshot(self, t: float) -> EnvSnapshot:
        """Create environment snapshot for the scheduler."""
        nodes = {}
        for i, sat in enumerate(self.satellites):
            pos = np.zeros(3)
            if self.positions is not None:
                # Find closest time index
                t_idx = min(int(t / self.config.dt), self.positions.shape[1] - 1)
                pos = self.positions[i, t_idx]

            nodes[i] = NodeSnapshot(
                node_id=i,
                role=sat.role.value,
                position=pos,
                compute_flops=sat.compute_flops if sat.compute_flops > 0 else self.config.compute_flops_default,
                battery_pct=self.energy.get_battery_pct(i),
                weight_cache=[],
            )

        active = self.contact_plan.get_active(t) if self.contact_plan else []

        return EnvSnapshot(
            current_time_s=t,
            nodes=nodes,
            contact_plan=self.contact_plan or ContactPlan([]),
            active_windows=active,
        )
