"""Energy model — Component-based power load tracking + battery dynamics.

Each satellite maintains a set of active power components. The total load
is recomputed each step from the active set (not via add/remove deltas),
eliminating drift bugs.

Energy timeline recording is built-in for per-satellite validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum
import numpy as np


class PowerMode(str, Enum):
    FULL = "full"
    LOW_POWER = "low_power"
    SAFE_MODE = "safe_mode"
    OFF = "off"


class PowerComponent(str, Enum):
    """Identifiable power draw components."""
    BASE = "base"             # OBC + ADCS + thermal (always on)
    DETECTOR = "detector"     # Payload sensor (天格探测器)
    COMM_TX = "comm_tx"       # Transmitting
    COMM_RX = "comm_rx"       # Receiving
    COMPUTE = "compute"       # AI inference active
    HEATER = "heater"         # Eclipse thermal management


@dataclass
class PowerProfile:
    """Power consumption values for each component (Watts)."""
    base_w: float = 2.0
    detector_w: float = 3.0
    comm_tx_w: float = 5.0
    comm_rx_w: float = 2.0
    compute_w: float = 15.0
    heater_w: float = 1.0

    def get_power(self, component: PowerComponent) -> float:
        return {
            PowerComponent.BASE: self.base_w,
            PowerComponent.DETECTOR: self.detector_w,
            PowerComponent.COMM_TX: self.comm_tx_w,
            PowerComponent.COMM_RX: self.comm_rx_w,
            PowerComponent.COMPUTE: self.compute_w,
            PowerComponent.HEATER: self.heater_w,
        }[component]


@dataclass
class BatteryState:
    """Per-node battery + solar state."""
    energy_j: float           # Current stored energy (Joules)
    capacity_j: float         # Max capacity (Joules)
    min_energy_j: float       # Deep-discharge protection threshold (SAFE_MODE)
    low_energy_j: float       # LOW_POWER threshold
    solar_panel_w: float      # Peak solar power (W)
    charge_efficiency: float = 0.90
    discharge_efficiency: float = 0.95
    power_mode: PowerMode = PowerMode.FULL
    eclipsed: bool = False

    # Component-based load tracking
    active_components: Dict[str, PowerComponent] = field(default_factory=dict)
    # key = unique operation id (e.g. "xfer_grb001_input"), value = component type
    # BASE is always implicitly active

    power_profile: PowerProfile = field(default_factory=PowerProfile)

    # Per-step computed values (for logging)
    _solar_input_w: float = field(default=0.0, repr=False)
    _total_load_w: float = field(default=0.0, repr=False)
    _net_power_w: float = field(default=0.0, repr=False)

    @property
    def pct(self) -> float:
        return self.energy_j / self.capacity_j * 100.0

    @property
    def solar_input_w(self) -> float:
        """Current solar input (0 if eclipsed)."""
        if self.eclipsed:
            return 0.0
        return self.solar_panel_w

    def compute_total_load(self) -> float:
        """Recompute total power draw from active components."""
        total = self.power_profile.base_w  # BASE always on
        for op_id, comp in self.active_components.items():
            total += self.power_profile.get_power(comp)
        # Heater in eclipse (thermal management)
        if self.eclipsed:
            total += self.power_profile.heater_w
        return total


@dataclass
class EnergyTimelineEntry:
    """One sample in a satellite's energy timeline."""
    t: float
    battery_pct: float
    solar_in_w: float
    total_load_w: float
    net_power_w: float
    is_eclipsed: bool
    power_mode: str
    active_ops: List[str]  # list of active component descriptions


class EnergyModel:
    """Component-based energy model for all nodes."""

    def __init__(self, num_nodes: int):
        self.num_nodes = num_nodes
        self.states: List[Optional[BatteryState]] = [None] * num_nodes
        # Energy timeline recording
        self._timelines: Dict[int, List[EnergyTimelineEntry]] = {}
        self._record_timeline: bool = True
        self._record_interval: float = 1.0  # Record every N seconds
        self._last_record_t: float = -999.0

    def init_node(self, node_id: int, solar_w: float, battery_wh: float,
                  min_pct: float = 20.0, low_pct: float = 30.0,
                  initial_pct: float = 80.0,
                  power_profile: Optional[PowerProfile] = None):
        """Initialize a node's energy state."""
        capacity_j = battery_wh * 3600.0
        profile = power_profile or PowerProfile()
        self.states[node_id] = BatteryState(
            energy_j=capacity_j * initial_pct / 100.0,
            capacity_j=capacity_j,
            min_energy_j=capacity_j * min_pct / 100.0,
            low_energy_j=capacity_j * low_pct / 100.0,
            solar_panel_w=solar_w,
            power_profile=profile,
        )
        self._timelines[node_id] = []

    # === Component-based load management ===

    def activate_component(self, node_id: int, op_id: str, component: PowerComponent):
        """Activate a power component for a specific operation."""
        state = self.states[node_id]
        if state is None:
            return
        state.active_components[op_id] = component

    def deactivate_component(self, node_id: int, op_id: str):
        """Deactivate a power component when operation ends."""
        state = self.states[node_id]
        if state is None:
            return
        state.active_components.pop(op_id, None)

    def has_active_component(self, node_id: int, component: PowerComponent) -> bool:
        """Check if any operation of given type is active."""
        state = self.states[node_id]
        if state is None:
            return False
        return component in state.active_components.values()

    # === Eclipse ===

    def set_eclipsed(self, node_id: int, eclipsed: bool):
        """Update eclipse state."""
        if self.states[node_id]:
            self.states[node_id].eclipsed = eclipsed

    # === Main step ===

    def step(self, t: float, dt: float) -> List[Dict]:
        """
        Update all batteries for one time step.
        Recomputes load from active components each step.
        Returns list of state-change events.
        """
        events = []
        for i in range(self.num_nodes):
            state = self.states[i]
            if state is None or state.power_mode == PowerMode.OFF:
                continue

            # Recompute load from components
            solar = state.solar_input_w
            load = state.compute_total_load()
            net = solar - load

            # Store for logging
            state._solar_input_w = solar
            state._total_load_w = load
            state._net_power_w = net

            if net > 0:
                # Charging
                delta_j = net * dt * state.charge_efficiency
                state.energy_j = min(state.energy_j + delta_j, state.capacity_j)
            else:
                # Discharging
                delta_j = abs(net) * dt / state.discharge_efficiency
                state.energy_j = max(0.0, state.energy_j - delta_j)

            # Check thresholds — hysteresis to prevent oscillation
            if state.energy_j <= state.min_energy_j:
                if state.power_mode != PowerMode.SAFE_MODE:
                    state.power_mode = PowerMode.SAFE_MODE
                    events.append({'type': 'power_mode_change', 'node': i,
                                   'mode': PowerMode.SAFE_MODE, 'time': t,
                                   'battery_pct': state.pct})
            elif state.energy_j <= state.low_energy_j:
                if state.power_mode == PowerMode.FULL:
                    state.power_mode = PowerMode.LOW_POWER
                    events.append({'type': 'power_mode_change', 'node': i,
                                   'mode': PowerMode.LOW_POWER, 'time': t,
                                   'battery_pct': state.pct})
            elif state.energy_j > state.low_energy_j * 1.1:
                # Hysteresis: recover to FULL only when above low + 10%
                if state.power_mode == PowerMode.LOW_POWER:
                    state.power_mode = PowerMode.FULL
                    events.append({'type': 'power_mode_change', 'node': i,
                                   'mode': PowerMode.FULL, 'time': t,
                                   'battery_pct': state.pct})
            elif state.energy_j > state.min_energy_j * 1.2:
                if state.power_mode == PowerMode.SAFE_MODE:
                    state.power_mode = PowerMode.LOW_POWER
                    events.append({'type': 'power_mode_change', 'node': i,
                                   'mode': PowerMode.LOW_POWER, 'time': t,
                                   'battery_pct': state.pct})

        # Record timeline
        if self._record_timeline and (t - self._last_record_t) >= self._record_interval:
            self._record_step(t)
            self._last_record_t = t

        return events

    def _record_step(self, t: float):
        """Record current state for all nodes."""
        for i in range(self.num_nodes):
            state = self.states[i]
            if state is None:
                continue
            ops = [f"{op_id}({comp.value})"
                   for op_id, comp in state.active_components.items()]
            entry = EnergyTimelineEntry(
                t=t,
                battery_pct=state.pct,
                solar_in_w=state._solar_input_w,
                total_load_w=state._total_load_w,
                net_power_w=state._net_power_w,
                is_eclipsed=state.eclipsed,
                power_mode=state.power_mode.value,
                active_ops=ops,
            )
            self._timelines[i].append(entry)

    # === Queries ===

    def get_battery_pct(self, node_id: int) -> float:
        state = self.states[node_id]
        return state.pct if state else 100.0

    def get_battery_energy_j(self, node_id: int) -> float:
        state = self.states[node_id]
        return state.energy_j if state else 0.0

    def can_compute(self, node_id: int) -> bool:
        """Check if node has enough power to compute."""
        state = self.states[node_id]
        if state is None:
            return True
        return state.power_mode == PowerMode.FULL

    def can_communicate(self, node_id: int) -> bool:
        """Check if node can communicate (not in SAFE_MODE)."""
        state = self.states[node_id]
        if state is None:
            return True
        return state.power_mode in (PowerMode.FULL, PowerMode.LOW_POWER)

    def estimate_energy_cost_j(self, node_id: int,
                               comm_duration_s: float = 0.0,
                               compute_duration_s: float = 0.0) -> float:
        """Estimate energy cost for a planned operation."""
        state = self.states[node_id]
        if state is None:
            return 0.0
        profile = state.power_profile
        cost = 0.0
        if comm_duration_s > 0:
            cost += profile.comm_tx_w * comm_duration_s
        if compute_duration_s > 0:
            cost += profile.compute_w * compute_duration_s
        return cost

    def has_enough_energy(self, node_id: int,
                          comm_duration_s: float = 0.0,
                          compute_duration_s: float = 0.0) -> bool:
        """Check if node has enough energy for a planned operation (above SAFE threshold)."""
        state = self.states[node_id]
        if state is None:
            return True
        cost_j = self.estimate_energy_cost_j(node_id, comm_duration_s, compute_duration_s)
        # Must remain above safe-mode threshold after the operation
        return (state.energy_j - cost_j) > state.min_energy_j

    # === Timeline export ===

    def get_timeline(self, node_id: int) -> List[EnergyTimelineEntry]:
        """Get recorded energy timeline for a node."""
        return self._timelines.get(node_id, [])

    def get_all_timelines(self) -> Dict[int, List[EnergyTimelineEntry]]:
        """Get all recorded timelines."""
        return self._timelines

    def export_timeline_csv(self, node_id: int) -> str:
        """Export a node's timeline as CSV string."""
        lines = ["t,battery_pct,solar_in_w,total_load_w,net_power_w,eclipsed,mode,active_ops"]
        for e in self._timelines.get(node_id, []):
            ops_str = "|".join(e.active_ops) if e.active_ops else "idle"
            lines.append(
                f"{e.t:.1f},{e.battery_pct:.2f},{e.solar_in_w:.1f},"
                f"{e.total_load_w:.1f},{e.net_power_w:.1f},"
                f"{int(e.is_eclipsed)},{e.power_mode},{ops_str}"
            )
        return "\n".join(lines)

    # === Legacy compatibility ===

    def set_load(self, node_id: int, power_w: float):
        """Legacy: set base load. Now handled via power_profile.base_w."""
        state = self.states[node_id]
        if state:
            state.power_profile.base_w = power_w

    def add_load(self, node_id: int, delta_w: float):
        """Legacy: no-op. Use activate_component/deactivate_component instead."""
        pass  # Intentionally ignored — components track load now
