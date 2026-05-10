"""DES Core — Custom discrete-event simulation engine.

Design choices (see Appendix F):
- Custom event heap (not SimPy) for batch preloading + adaptive time-skip
- Mixed time advance: fixed Δt for orbital updates + event queue for async events
- Vectorized step callbacks for 2800+ node scalability
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any
from enum import Enum, auto


class EventType(str, Enum):
    # Orbital / physical (precomputed, batch-inserted)
    LINK_UP = "link_up"
    LINK_DOWN = "link_down"
    ECLIPSE_ENTER = "eclipse_enter"
    ECLIPSE_EXIT = "eclipse_exit"
    
    # Task (runtime)
    TASK_ARRIVE = "task_arrive"
    COMPUTE_START = "compute_start"
    COMPUTE_DONE = "compute_done"
    TRANSFER_START = "transfer_start"
    TRANSFER_DONE = "transfer_done"
    TASK_COMPLETE = "task_complete"
    TASK_FAILED = "task_failed"
    
    # Energy
    ENERGY_WARNING = "energy_warning"
    ENERGY_DEPLETED = "energy_depleted"
    POWER_MODE_CHANGE = "power_mode_change"
    
    # Scheduler
    SCHEDULER_TRIGGER = "scheduler_trigger"


@dataclass(order=True)
class Event:
    """A discrete event in the simulation."""
    time: float
    priority: int = field(default=5, compare=True)
    type: EventType = field(compare=False, default=EventType.TASK_ARRIVE)
    payload: Dict[str, Any] = field(compare=False, default_factory=dict)
    id: str = field(compare=False, default="")

    def __repr__(self):
        return f"Event(t={self.time:.1f}, {self.type.value}, {self.payload})"


# Event priority (lower = processed first at same time)
EVENT_PRIORITY: Dict[EventType, int] = {
    EventType.ECLIPSE_ENTER: 0,
    EventType.ECLIPSE_EXIT: 0,
    EventType.LINK_UP: 1,
    EventType.LINK_DOWN: 1,
    EventType.ENERGY_DEPLETED: 2,
    EventType.POWER_MODE_CHANGE: 2,
    EventType.COMPUTE_DONE: 3,
    EventType.TRANSFER_DONE: 3,
    EventType.TASK_ARRIVE: 4,
    EventType.TASK_COMPLETE: 4,
    EventType.TASK_FAILED: 4,
    EventType.SCHEDULER_TRIGGER: 9,
}


class DESEngine:
    """Custom discrete-event simulation engine with adaptive time-skip."""

    def __init__(self, duration_s: float, dt: float = 1.0, max_skip_s: float = 60.0):
        self.duration = duration_s
        self.dt = dt
        self.max_skip_s = max_skip_s
        self.clock: float = 0.0

        # Event heap
        self._heap: List[Event] = []
        self._event_counter: int = 0

        # Callbacks
        self._step_callbacks: List[Callable[[float, float], None]] = []
        self._event_handlers: Dict[EventType, List[Callable[[Event], None]]] = {}

        # State
        self._idle_checker: Optional[Callable[[], bool]] = None
        self._running = False
        self.events_processed: int = 0

    def schedule(self, event: Event) -> None:
        """Schedule a single event."""
        if event.priority == 5:  # default, assign from table
            event.priority = EVENT_PRIORITY.get(event.type, 5)
        heapq.heappush(self._heap, event)

    def schedule_batch(self, events: List[Event]) -> None:
        """Batch-insert events and heapify once (faster for precomputed events)."""
        for e in events:
            if e.priority == 5:
                e.priority = EVENT_PRIORITY.get(e.type, 5)
            self._heap.append(e)
        heapq.heapify(self._heap)

    def register_step_callback(self, fn: Callable[[float, float], None]) -> None:
        """Register a function called every Δt: fn(current_time, dt)."""
        self._step_callbacks.append(fn)

    def register_handler(self, event_type: EventType, fn: Callable[[Event], None]) -> None:
        """Register an event handler."""
        self._event_handlers.setdefault(event_type, []).append(fn)

    def set_idle_checker(self, fn: Callable[[], bool]) -> None:
        """Set a function that returns True when simulation is idle (enables skip)."""
        self._idle_checker = fn

    def run(self) -> None:
        """Run the simulation from current clock to duration."""
        self._running = True
        while self._running and self.clock < self.duration:
            # Phase 1: Process all events at current time
            while self._heap and self._heap[0].time <= self.clock:
                event = heapq.heappop(self._heap)
                self._dispatch(event)
                self.events_processed += 1

            # Phase 2: Step callbacks
            for cb in self._step_callbacks:
                cb(self.clock, self.dt)

            # Phase 3: Advance clock
            self.clock = self._advance_clock()

        self._running = False

    def stop(self) -> None:
        """Stop the simulation."""
        self._running = False

    def _dispatch(self, event: Event) -> None:
        """Dispatch event to registered handlers."""
        handlers = self._event_handlers.get(event.type, [])
        for handler in handlers:
            handler(event)

    def _advance_clock(self) -> float:
        """Advance clock with adaptive skip when idle."""
        next_step = self.clock + self.dt

        # Skip optimization
        if self._idle_checker and self._idle_checker():
            if self._heap:
                next_event = self._heap[0].time
                max_jump = self.clock + self.max_skip_s
                return min(next_event, next_step, max_jump)
            else:
                # No events at all — jump to end or max_skip
                return min(self.clock + self.max_skip_s, self.duration)

        return next_step

    @property
    def pending_events(self) -> int:
        return len(self._heap)
