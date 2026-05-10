"""Visualization data exporter — Converts simulation state to JSON for 3D playback.

Captures positions, events, transfers, energy, and compute jobs during simulation,
then exports as the JSON format expected by the OASIS Viz frontend.
"""

from __future__ import annotations

import json
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any


@dataclass
class VizEvent:
    """A discrete event for the timeline."""
    t: float
    type: str
    detail: str
    node: int = -1  # Related node (-1 = global)


@dataclass
class VizTransfer:
    """A data transfer for animated flow visualization."""
    src: int
    dst: int
    start_s: float
    end_s: float
    size_bytes: int
    purpose: str  # "input" / "result" / "relay" / "weight"
    task_id: str = ""


@dataclass
class VizComputeJob:
    """A computation job with progress tracking."""
    node: int
    task_id: str
    subtask_id: str
    start_s: float
    end_s: float
    total_flops: float


@dataclass
class VizContactWindow:
    """A contact window for link availability display."""
    src: int
    dst: int
    start_s: float
    end_s: float
    rate_mbps: float


class VizRecorder:
    """
    Records simulation state for visualization export.
    Attach to a Simulator instance to capture data during run.
    """

    def __init__(self, position_sample_interval_s: float = 1.0,
                 energy_sample_interval_s: float = 1.0):
        self.position_sample_interval = position_sample_interval_s
        self.energy_sample_interval = energy_sample_interval_s

        # Scenario metadata
        self.scenario_name: str = ""
        self.duration_s: float = 0.0
        self.dt: float = 1.0

        # Satellite definitions
        self.satellites: List[Dict[str, Any]] = []

        # Position time series (downsampled)
        self.position_times: List[float] = []
        self.position_data: List[List[List[float]]] = []  # [sat_idx][time_idx][x,y,z]

        # Events log
        self.events: List[VizEvent] = []

        # Transfer log
        self.transfers: List[VizTransfer] = []

        # Compute jobs
        self.compute_jobs: List[VizComputeJob] = []

        # Contact windows
        self.contact_windows: List[VizContactWindow] = []

        # Energy samples
        self.energy_times: List[float] = []
        self.energy_data: Dict[int, List[float]] = {}  # node_id → [pct, pct, ...]

        # Internal tracking
        self._last_position_sample: float = -999.0
        self._last_energy_sample: float = -999.0
        self._num_sats: int = 0

    def init_from_simulator(self, sim) -> None:
        """Initialize recorder from a configured Simulator instance."""
        from oasis.orbital.constellation import Role

        self.scenario_name = "oasis_simulation"
        self.duration_s = sim.config.duration_s
        self.dt = sim.config.dt
        self._num_sats = len(sim.satellites)

        # Define color scheme per role
        role_colors = {
            Role.DETECTOR: "#4299e1",   # Blue
            Role.COMPUTE: "#48bb78",    # Green
            Role.RELAY: "#ed8936",      # Orange
            Role.HYBRID: "#9f7aea",     # Purple
            Role.GROUND: "#a0aec0",     # Gray
        }

        # Satellite metadata
        self.satellites = []
        for i, sat in enumerate(sim.satellites):
            self.satellites.append({
                "id": sat.id,
                "role": sat.role.value,
                "color": role_colors.get(sat.role, "#a0aec0"),
                "compute_flops": sat.compute_flops,
                "orbit": {
                    "semi_major_axis_km": sat.elements.semi_major_axis_km,
                    "inclination_deg": sat.elements.inclination_deg,
                    "raan_deg": sat.elements.raan_deg,
                    "arg_perigee_deg": sat.elements.arg_perigee_deg,
                    "true_anomaly_deg": sat.elements.true_anomaly_deg,
                },
            })

        # Init position storage
        self.position_data = [[] for _ in range(self._num_sats)]

        # Init energy storage
        for i in range(self._num_sats):
            self.energy_data[i] = []

        # Record contact windows
        if sim.contact_plan:
            for w in sim.contact_plan.windows:
                self.contact_windows.append(VizContactWindow(
                    src=w.src, dst=w.dst,
                    start_s=w.start_s, end_s=w.end_s,
                    rate_mbps=w.avg_rate_bps / 1e6,
                ))

    def sample_positions(self, t: float, sim) -> None:
        """Sample satellite positions at current time (called each step)."""
        if t - self._last_position_sample < self.position_sample_interval - 0.001:
            return
        self._last_position_sample = t

        self.position_times.append(round(t, 2))

        if sim.positions is not None:
            t_idx = min(int(t / sim.config.dt), sim.positions.shape[1] - 1)
            for i in range(self._num_sats):
                pos = sim.positions[i, t_idx].tolist()
                self.position_data[i].append([round(x, 2) for x in pos])
        else:
            # No orbital propagation — use zero positions
            for i in range(self._num_sats):
                self.position_data[i].append([0.0, 0.0, 0.0])

    def sample_energy(self, t: float, sim) -> None:
        """Sample battery state (called each step)."""
        if t - self._last_energy_sample < self.energy_sample_interval - 0.001:
            return
        self._last_energy_sample = t

        self.energy_times.append(round(t, 2))
        for i in range(self._num_sats):
            pct = sim.energy.get_battery_pct(i)
            self.energy_data[i].append(round(pct, 1))

    def record_event(self, t: float, event_type: str, detail: str, node: int = -1):
        """Record a discrete event."""
        self.events.append(VizEvent(
            t=round(t, 2), type=event_type, detail=detail, node=node
        ))

    def record_transfer_start(self, t: float, src: int, dst: int,
                              size_bytes: int, purpose: str, task_id: str = ""):
        """Record start of a data transfer (end will be updated later)."""
        self.transfers.append(VizTransfer(
            src=src, dst=dst,
            start_s=round(t, 2), end_s=-1.0,
            size_bytes=size_bytes,
            purpose=purpose,
            task_id=task_id,
        ))

    def record_transfer_end(self, t: float, src: int, dst: int, purpose: str):
        """Update end time of a transfer."""
        # Find matching transfer (last one with same src/dst/purpose)
        for xfer in reversed(self.transfers):
            if xfer.src == src and xfer.dst == dst and xfer.purpose == purpose and xfer.end_s < 0:
                xfer.end_s = round(t, 2)
                return

    def record_compute_start(self, t: float, node: int, task_id: str,
                             subtask_id: str, total_flops: float):
        """Record start of computation."""
        self.compute_jobs.append(VizComputeJob(
            node=node, task_id=task_id, subtask_id=subtask_id,
            start_s=round(t, 2), end_s=-1.0, total_flops=total_flops,
        ))

    def record_compute_end(self, t: float, node: int, subtask_id: str):
        """Update end time of computation."""
        for job in reversed(self.compute_jobs):
            if job.node == node and job.subtask_id == subtask_id and job.end_s < 0:
                job.end_s = round(t, 2)
                return

    def export_json(self, pretty: bool = False) -> str:
        """Export all recorded data as JSON string."""
        data = {
            "scenario": {
                "name": self.scenario_name,
                "duration_s": self.duration_s,
                "dt": self.dt,
            },
            "satellites": self.satellites,
            "positions": {
                "times": self.position_times,
                "data": self.position_data,
            },
            "contact_windows": [
                {"src": w.src, "dst": w.dst, "start": w.start_s,
                 "end": w.end_s, "rate_mbps": w.rate_mbps}
                for w in self.contact_windows
            ],
            "events": [
                {"t": e.t, "type": e.type, "detail": e.detail, "node": e.node}
                for e in self.events
            ],
            "transfers": [
                {"src": x.src, "dst": x.dst, "start": x.start_s, "end": x.end_s,
                 "bytes": x.size_bytes, "purpose": x.purpose, "task_id": x.task_id}
                for x in self.transfers
            ],
            "compute_jobs": [
                {"node": j.node, "task_id": j.task_id, "subtask": j.subtask_id,
                 "start": j.start_s, "end": j.end_s, "flops": j.total_flops}
                for j in self.compute_jobs
            ],
            "energy": {
                "times": self.energy_times,
                "data": {str(k): v for k, v in self.energy_data.items()},
            },
        }

        if pretty:
            return json.dumps(data, indent=2, ensure_ascii=False)
        return json.dumps(data, separators=(',', ':'), ensure_ascii=False)

    def export_to_file(self, path: str, pretty: bool = True) -> None:
        """Export to a JSON file."""
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.export_json(pretty=pretty))
