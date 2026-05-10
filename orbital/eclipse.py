"""Eclipse model — Determine when satellites are in Earth's shadow.

Uses cylindrical shadow model (sufficient for LEO).
Integrates with energy model to cut solar input during eclipse.
"""

from __future__ import annotations

import numpy as np
from typing import List, Tuple
from oasis.orbital.constellation import R_EARTH_KM


def compute_sun_direction(t_s: float, epoch_jd_offset: float = 0.0) -> np.ndarray:
    """
    Approximate sun direction in ECI frame.
    
    Uses simple Earth-orbit model: Earth orbits sun in ~365.25 days.
    At epoch, sun is along +X axis. Good enough for eclipse geometry.
    """
    # Earth's orbital period in seconds
    year_s = 365.25 * 86400.0
    # Angular position of Earth around sun (sun direction = -Earth position)
    angle = 2 * np.pi * (t_s + epoch_jd_offset * 86400) / year_s
    # Sun direction (from Earth toward Sun) in ECI
    return np.array([np.cos(angle), np.sin(angle), 0.0])


def is_eclipsed_cylindrical(sat_pos_km: np.ndarray, sun_dir: np.ndarray) -> bool:
    """
    Cylindrical shadow model: satellite is eclipsed if it's behind Earth
    relative to the sun direction.
    
    Args:
        sat_pos_km: Satellite position in ECI (km), shape (3,)
        sun_dir: Unit vector toward sun, shape (3,)
    
    Returns:
        True if satellite is in Earth's shadow
    """
    # Project satellite position onto sun direction
    proj = np.dot(sat_pos_km, sun_dir)
    
    if proj > 0:
        # Satellite is on the sun side → not eclipsed
        return False
    
    # Distance from satellite to the Earth-Sun line
    perp = sat_pos_km - proj * sun_dir
    perp_dist = np.linalg.norm(perp)
    
    # Eclipsed if perpendicular distance < Earth radius
    return perp_dist < R_EARTH_KM


def compute_eclipse_schedule(
    positions: np.ndarray,
    times_s: np.ndarray,
    epoch_jd_offset: float = 0.0,
) -> List[List[Tuple[float, float]]]:
    """
    Compute eclipse windows for all satellites.
    
    Args:
        positions: (N, T, 3) satellite positions in ECI (km)
        times_s: (T,) time array in seconds
    
    Returns:
        List of N lists, each containing (enter_time, exit_time) tuples
    """
    N, T, _ = positions.shape
    eclipse_windows = [[] for _ in range(N)]
    
    for i in range(N):
        in_eclipse = False
        enter_time = 0.0
        
        for t_idx in range(T):
            t = times_s[t_idx]
            sun_dir = compute_sun_direction(t, epoch_jd_offset)
            eclipsed = is_eclipsed_cylindrical(positions[i, t_idx], sun_dir)
            
            if eclipsed and not in_eclipse:
                in_eclipse = True
                enter_time = t
            elif not eclipsed and in_eclipse:
                in_eclipse = False
                eclipse_windows[i].append((enter_time, t))
        
        # Handle case where eclipse extends to end
        if in_eclipse:
            eclipse_windows[i].append((enter_time, times_s[-1]))
    
    return eclipse_windows


def compute_eclipse_schedule_vectorized(
    positions: np.ndarray,
    times_s: np.ndarray,
    epoch_jd_offset: float = 0.0,
) -> Tuple[np.ndarray, List[List[Tuple[float, float]]]]:
    """
    Vectorized eclipse computation for all satellites at all times.
    
    Returns:
        eclipsed: (N, T) boolean array
        windows: List of eclipse windows per satellite
    """
    N, T, _ = positions.shape
    eclipsed = np.zeros((N, T), dtype=bool)
    
    for t_idx in range(T):
        t = times_s[t_idx]
        sun_dir = compute_sun_direction(t, epoch_jd_offset)
        
        # Vectorized over all satellites at this time step
        pos = positions[:, t_idx, :]  # (N, 3)
        proj = np.dot(pos, sun_dir)   # (N,)
        
        # Behind Earth (proj < 0)
        behind = proj < 0
        
        # Perpendicular distance to sun line
        perp = pos - np.outer(proj, sun_dir)  # (N, 3)
        perp_dist = np.linalg.norm(perp, axis=1)  # (N,)
        
        # Eclipsed = behind AND within Earth radius
        eclipsed[:, t_idx] = behind & (perp_dist < R_EARTH_KM)
    
    # Extract windows from boolean array
    windows = []
    for i in range(N):
        sat_windows = []
        in_eclipse = False
        enter_time = 0.0
        for t_idx in range(T):
            if eclipsed[i, t_idx] and not in_eclipse:
                in_eclipse = True
                enter_time = times_s[t_idx]
            elif not eclipsed[i, t_idx] and in_eclipse:
                in_eclipse = False
                sat_windows.append((enter_time, times_s[t_idx]))
        if in_eclipse:
            sat_windows.append((enter_time, times_s[-1]))
        windows.append(sat_windows)
    
    return eclipsed, windows
