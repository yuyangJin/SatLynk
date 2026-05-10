"""Contact Plan — Precompute communication windows between satellites.

Given positions over time + link rules, outputs a list of ContactWindow objects
that the scheduler uses for planning.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional
from bisect import bisect_left, bisect_right

from oasis.orbital.constellation import (
    Satellite, propagate_positions, check_line_of_sight, R_EARTH_KM
)


@dataclass
class ContactWindow:
    """A time interval during which two nodes can communicate."""
    src: int              # Source node index
    dst: int              # Destination node index
    start_s: float        # Window start time
    end_s: float          # Window end time
    avg_rate_bps: float   # Average data rate during window
    min_distance_km: float  # Closest approach
    max_distance_km: float  # Farthest point in window

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def capacity_bits(self) -> float:
        """Total data that can be transferred in this window."""
        return self.avg_rate_bps * self.duration_s

    def is_active(self, t: float) -> bool:
        return self.start_s <= t < self.end_s

    def __repr__(self):
        return (f"Contact({self.src}→{self.dst}, "
                f"t=[{self.start_s:.1f}, {self.end_s:.1f}], "
                f"rate={self.avg_rate_bps/1e6:.1f} Mbps)")


class ContactPlan:
    """Precomputed set of all communication windows for a scenario."""

    def __init__(self, windows: List[ContactWindow]):
        self.windows = sorted(windows, key=lambda w: w.start_s)
        # Build index for fast lookup
        self._by_node: dict = {}
        for w in self.windows:
            self._by_node.setdefault(w.src, []).append(w)
            self._by_node.setdefault(w.dst, []).append(w)

    def get_active(self, t: float) -> List[ContactWindow]:
        """Get all windows active at time t."""
        return [w for w in self.windows if w.is_active(t)]

    def get_active_for_node(self, node: int, t: float) -> List[ContactWindow]:
        """Get windows active at time t involving a specific node."""
        return [w for w in self._by_node.get(node, []) if w.is_active(t)]

    def get_future(self, node: int, t: float, horizon_s: float) -> List[ContactWindow]:
        """Get future windows for a node within horizon."""
        return [
            w for w in self._by_node.get(node, [])
            if w.start_s >= t and w.start_s < t + horizon_s
        ]

    def get_window(self, src: int, dst: int, t: float) -> Optional[ContactWindow]:
        """Get specific window between src and dst at time t."""
        for w in self._by_node.get(src, []):
            if w.dst == dst and w.is_active(t):
                return w
            if w.src == dst and w.is_active(t):
                return w
        return None

    def __len__(self):
        return len(self.windows)

    def __repr__(self):
        return f"ContactPlan({len(self.windows)} windows)"


def compute_contact_plan(
    satellites: List[Satellite],
    times_s: np.ndarray,
    positions: np.ndarray,
    max_range_km: Optional[float] = None,
    data_rate_bps: float = 10e6,  # Default 10 Mbps
    candidate_pairs: Optional[List[Tuple[int, int]]] = None,
) -> ContactPlan:
    """
    Compute the contact plan for a set of satellites.
    
    Args:
        satellites: List of satellite objects
        times_s: Time array (seconds from epoch)
        positions: Shape (N, T, 3) satellite positions
        max_range_km: Maximum communication range (None = use per-sat value)
        data_rate_bps: Fixed data rate when link is up (Phase 1 simplified)
        candidate_pairs: If provided, only compute for these (i,j) pairs
    
    Returns:
        ContactPlan with all communication windows
    """
    N = len(satellites)
    T = len(times_s)
    dt = times_s[1] - times_s[0] if T > 1 else 1.0

    # Determine candidate pairs
    if candidate_pairs is None:
        # Default: all pairs
        candidate_pairs = [(i, j) for i in range(N) for j in range(i+1, N)]

    windows: List[ContactWindow] = []

    for (i, j) in candidate_pairs:
        # Determine max range
        range_i = satellites[i].max_comm_range_km
        range_j = satellites[j].max_comm_range_km
        effective_range = min(range_i, range_j)
        if max_range_km is not None:
            effective_range = min(effective_range, max_range_km)

        # Compute distance series
        diff = positions[i] - positions[j]  # (T, 3)
        dist = np.linalg.norm(diff, axis=1)  # (T,)

        # Check line of sight
        los = check_line_of_sight(positions[i], positions[j])  # (T,)

        # Link available: within range AND line of sight
        link_up = (dist <= effective_range) & los

        # Extract continuous windows (runs of True)
        window_list = _extract_windows(link_up, times_s, dist)

        for (t_start, t_end, d_min, d_max) in window_list:
            windows.append(ContactWindow(
                src=i,
                dst=j,
                start_s=t_start,
                end_s=t_end,
                avg_rate_bps=data_rate_bps,  # Phase 1: fixed rate
                min_distance_km=d_min,
                max_distance_km=d_max,
            ))

    return ContactPlan(windows)


def _extract_windows(
    link_up: np.ndarray,
    times_s: np.ndarray,
    distances: np.ndarray,
) -> List[Tuple[float, float, float, float]]:
    """
    Extract continuous True intervals from boolean array.
    
    Returns: List of (start_time, end_time, min_distance, max_distance)
    """
    windows = []
    in_window = False
    start_idx = 0

    for idx in range(len(link_up)):
        if link_up[idx] and not in_window:
            # Window starts
            in_window = True
            start_idx = idx
        elif not link_up[idx] and in_window:
            # Window ends
            in_window = False
            t_start = times_s[start_idx]
            t_end = times_s[idx]  # End at the step where it goes down
            d_segment = distances[start_idx:idx]
            windows.append((t_start, t_end, d_segment.min(), d_segment.max()))

    # Handle window that extends to end of time
    if in_window:
        t_start = times_s[start_idx]
        t_end = times_s[-1]
        d_segment = distances[start_idx:]
        windows.append((t_start, t_end, d_segment.min(), d_segment.max()))

    return windows
