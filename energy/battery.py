"""Energy model — Simple battery dynamics for Phase 1.

Tracks per-node energy: solar charging, load consumption, state transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
import numpy as np


class PowerMode(str, Enum):
    FULL = "full"
    LOW_POWER = "low_power"
    SAFE_MODE = "safe_mode"
    OFF = "off"


@dataclass
class BatteryState:
    """Per-node battery state."""
    energy_j: float           # Current stored energy (Joules)
    capacity_j: float         # Max capacity (Joules)
    min_energy_j: float       # Deep-discharge protection threshold
    solar_panel_w: float      # Peak solar power (W)
    charge_efficiency: float = 0.9
    discharge_efficiency: float = 0.95
    power_mode: PowerMode = PowerMode.FULL
    eclipsed: bool = False

    @property
    def pct(self) -> float:
        return self.energy_j / self.capacity_j * 100.0

    @property
    def solar_input_w(self) -> float:
        """Current solar input (0 if eclipsed)."""
        if self.eclipsed:
            return 0.0
        return self.solar_panel_w


class EnergyModel:
    """Simple energy model for all nodes."""

    def __init__(self, num_nodes: int):
        self.num_nodes = num_nodes
        self.states: List[Optional[BatteryState]] = [None] * num_nodes
        self.loads_w: np.ndarray = np.zeros(num_nodes)  # Current load per node

    def init_node(self, node_id: int, solar_w: float, battery_wh: float,
                  min_pct: float = 20.0, initial_pct: float = 80.0):
        """Initialize a node's energy state."""
        capacity_j = battery_wh * 3600.0
        self.states[node_id] = BatteryState(
            energy_j=capacity_j * initial_pct / 100.0,
            capacity_j=capacity_j,
            min_energy_j=capacity_j * min_pct / 100.0,
            solar_panel_w=solar_w,
        )

    def set_load(self, node_id: int, power_w: float):
        """Set current power load for a node."""
        self.loads_w[node_id] = power_w

    def add_load(self, node_id: int, delta_w: float):
        """Add/remove load component."""
        self.loads_w[node_id] += delta_w

    def set_eclipsed(self, node_id: int, eclipsed: bool):
        """Update eclipse state."""
        if self.states[node_id]:
            self.states[node_id].eclipsed = eclipsed

    def step(self, t: float, dt: float) -> List[Dict]:
        """
        Update all batteries for one time step.
        Returns list of state-change events.
        """
        events = []
        for i in range(self.num_nodes):
            state = self.states[i]
            if state is None or state.power_mode == PowerMode.OFF:
                continue

            solar = state.solar_input_w
            load = self.loads_w[i]
            net = solar - load

            if net > 0:
                # Charging
                delta = net * dt * state.charge_efficiency
                state.energy_j = min(state.energy_j + delta, state.capacity_j)
            else:
                # Discharging
                delta = abs(net) * dt / state.discharge_efficiency
                state.energy_j -= delta

            # Check thresholds
            if state.energy_j <= state.min_energy_j:
                if state.power_mode != PowerMode.SAFE_MODE:
                    state.power_mode = PowerMode.SAFE_MODE
                    events.append({'type': 'power_mode_change', 'node': i,
                                   'mode': PowerMode.SAFE_MODE, 'time': t})
            elif state.energy_j <= state.capacity_j * 0.3:
                if state.power_mode == PowerMode.FULL:
                    state.power_mode = PowerMode.LOW_POWER
                    events.append({'type': 'power_mode_change', 'node': i,
                                   'mode': PowerMode.LOW_POWER, 'time': t})
            elif state.energy_j > state.capacity_j * 0.4:
                if state.power_mode == PowerMode.LOW_POWER:
                    state.power_mode = PowerMode.FULL
                    events.append({'type': 'power_mode_change', 'node': i,
                                   'mode': PowerMode.FULL, 'time': t})

        return events

    def get_battery_pct(self, node_id: int) -> float:
        state = self.states[node_id]
        return state.pct if state else 100.0

    def can_compute(self, node_id: int) -> bool:
        state = self.states[node_id]
        if state is None:
            return True
        return state.power_mode == PowerMode.FULL
