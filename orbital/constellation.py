"""Orbital module — Constellation generation, propagation, visibility.

Phase 1: Simplified model (no SGP4 dependency yet).
Uses Keplerian two-body for circular orbits — sufficient for toy case.
SGP4/Skyfield integration in Phase 2.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum


class Role(str, Enum):
    COMPUTE = "compute"
    DETECTOR = "detector"
    RELAY = "relay"
    HYBRID = "hybrid"
    GROUND = "ground"


@dataclass
class OrbitalElements:
    """Keplerian orbital elements (circular orbit simplification)."""
    semi_major_axis_km: float   # a = R_E + altitude
    inclination_deg: float      # i
    raan_deg: float = 0.0       # Ω (Right Ascension of Ascending Node)
    arg_perigee_deg: float = 0.0  # ω (0 for circular)
    true_anomaly_deg: float = 0.0  # ν at epoch
    eccentricity: float = 0.0  # e ≈ 0 for circular LEO


@dataclass
class Satellite:
    """A satellite instance in the simulation."""
    id: str
    role: Role
    elements: OrbitalElements
    
    # Hardware params (Phase 1 simplified)
    compute_flops: float = 0.0        # Peak FLOPS
    storage_bytes: int = 0
    max_comm_range_km: float = 5000.0
    power_solar_w: float = 50.0
    battery_capacity_wh: float = 200.0
    
    def __repr__(self):
        return f"Sat({self.id}, {self.role.value})"


# Constants
R_EARTH_KM = 6371.0
MU_EARTH = 398600.4418  # km³/s², gravitational parameter


def orbital_period(a_km: float) -> float:
    """Orbital period in seconds for semi-major axis a (km)."""
    return 2 * np.pi * np.sqrt(a_km**3 / MU_EARTH)


def mean_motion(a_km: float) -> float:
    """Mean motion in rad/s."""
    return np.sqrt(MU_EARTH / a_km**3)


def generate_walker_delta(
    total_sats: int,
    num_planes: int,
    phase_factor: int,
    altitude_km: float,
    inclination_deg: float,
    role: Role = Role.COMPUTE,
    prefix: str = "SAT",
    **sat_kwargs,
) -> List[Satellite]:
    """
    Generate a Walker-Delta constellation.
    
    Walker(N/P/F, h, i):
      - P planes, each with N/P satellites
      - RAAN spacing = 360°/P
      - In-plane spacing = 360°/(N/P)  
      - Cross-plane phase shift = F × 360°/N
    """
    sats_per_plane = total_sats // num_planes
    a_km = R_EARTH_KM + altitude_km
    satellites = []

    for j in range(num_planes):
        raan = j * 360.0 / num_planes
        for k in range(sats_per_plane):
            nu = k * 360.0 / sats_per_plane + j * phase_factor * 360.0 / total_sats
            nu = nu % 360.0
            
            sat_id = f"{prefix}-{j:03d}-{k:03d}"
            elements = OrbitalElements(
                semi_major_axis_km=a_km,
                inclination_deg=inclination_deg,
                raan_deg=raan,
                true_anomaly_deg=nu,
            )
            sat = Satellite(id=sat_id, role=role, elements=elements, **sat_kwargs)
            satellites.append(sat)

    return satellites


def propagate_positions(
    satellites: List[Satellite],
    times_s: np.ndarray,
    epoch_s: float = 0.0,
) -> np.ndarray:
    """
    Propagate satellite positions over time.
    
    Returns:
        positions: shape (N_sats, N_times, 3) in ECI frame (km)
    
    Phase 1: Simple Keplerian circular orbit (no perturbations).
    """
    N = len(satellites)
    T = len(times_s)
    positions = np.zeros((N, T, 3))

    for idx, sat in enumerate(satellites):
        a = sat.elements.semi_major_axis_km
        i = np.radians(sat.elements.inclination_deg)
        raan = np.radians(sat.elements.raan_deg)
        nu0 = np.radians(sat.elements.true_anomaly_deg)
        n = mean_motion(a)  # rad/s

        for t_idx, t in enumerate(times_s):
            # True anomaly at time t (circular orbit: ν = ν₀ + n*t)
            nu = nu0 + n * (t - epoch_s)

            # Position in orbital plane
            x_orb = a * np.cos(nu)
            y_orb = a * np.sin(nu)

            # Rotate to ECI (simplified: ignoring arg_perigee for circular orbit)
            # R = Rz(-Ω) × Rx(-i) × Rz(-ω)
            # For circular orbit with ω=0:
            cos_raan = np.cos(raan)
            sin_raan = np.sin(raan)
            cos_i = np.cos(i)
            sin_i = np.sin(i)

            x_eci = x_orb * cos_raan - y_orb * sin_raan * cos_i
            y_eci = x_orb * sin_raan + y_orb * cos_raan * cos_i
            z_eci = y_orb * sin_i

            positions[idx, t_idx] = [x_eci, y_eci, z_eci]

    return positions


def compute_distances(positions: np.ndarray) -> np.ndarray:
    """
    Compute pairwise distances between all satellites at each time step.
    
    Args:
        positions: (N, T, 3)
    Returns:
        distances: (N, N, T)
    """
    N, T, _ = positions.shape
    # Vectorized: d[i,j,t] = ||pos[i,t] - pos[j,t]||
    # Use broadcasting: (N,1,T,3) - (1,N,T,3) → (N,N,T,3) → norm → (N,N,T)
    diff = positions[:, np.newaxis, :, :] - positions[np.newaxis, :, :, :]
    distances = np.linalg.norm(diff, axis=3)
    return distances


def check_line_of_sight(pos_i: np.ndarray, pos_j: np.ndarray) -> np.ndarray:
    """
    Check line-of-sight between two satellites (not blocked by Earth).
    
    Args:
        pos_i, pos_j: shape (T, 3) — positions over time
    Returns:
        los: shape (T,) boolean array
    """
    # Parametric line: P(λ) = pos_i + λ * (pos_j - pos_i), λ ∈ [0, 1]
    # Minimum distance to origin: solve d/dλ |P(λ)|² = 0
    d = pos_j - pos_i  # (T, 3)
    
    # λ_min = -dot(pos_i, d) / dot(d, d)
    dot_id = np.sum(pos_i * d, axis=1)  # (T,)
    dot_dd = np.sum(d * d, axis=1)      # (T,)
    
    # Avoid division by zero (same position)
    dot_dd = np.maximum(dot_dd, 1e-10)
    lam = -dot_id / dot_dd
    
    # Clamp to [0, 1]
    lam = np.clip(lam, 0.0, 1.0)
    
    # Closest point on segment
    closest = pos_i + lam[:, np.newaxis] * d  # (T, 3)
    min_dist = np.linalg.norm(closest, axis=1)  # (T,)
    
    # LOS exists if minimum distance > R_Earth (with margin for atmosphere)
    R_MARGIN = R_EARTH_KM + 100.0  # 100 km atmosphere margin
    los = min_dist > R_MARGIN
    
    return los
