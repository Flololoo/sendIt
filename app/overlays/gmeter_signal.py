"""G-meter signal: gravity-free acceleration, travel direction, horizontal g and bump events.

Frame conventions (shared with `lean_signal`):
- `rotation_matrices(quat)` with `CONVENTION` maps camera axes to the world frame.
- `gravity_in_camera` is the reading of an accelerometer at rest, in camera axes, so
  subtracting it leaves the linear acceleration of the camera (the spec's a_cam - g_cam).
- Only the horizontal components enter the meter. The heading is the camera's viewing axis
  (camera x) projected onto the horizontal plane.
- The world frame has +z pointing down, so it is left-handed seen from above and the right of
  the heading is (-f_y, f_x). Checked on the whole of clip 0051: lateral then correlates
  +0.98 with tan(lean) in steady curves (right lean = positive).
- Longitudinal is positive when accelerating. The sign follows from the spec's
  a_cam - g_cam convention. Consistent with clip 0051: gentle positive values when pulling away
  and negative values when approaching the final stop.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from dataclasses import dataclass

import numpy as np

from app.telemetry import Samples

from .contract import Mount
from .lean_signal import gravity_in_camera, hann_smooth, lowpass, rotation_matrices, VIEW_AXIS

TRAVEL_SMOOTH_S: dict[str, float] = {"bike": 0.5, "helmet": 2.5}
HELMET_TURN_RATE_LIMIT_DEG_S = 45.0
METER_SMOOTH_S = 0.4
BUMP_TREND_S = 1.0
BUMP_MERGE_S = 1.0

# Peak thresholds on the detrended vertical residual, in g. Starting values, tuned on footage.
BUMP_THRESHOLDS_G: dict[str, float] = {"low": 1.2, "medium": 0.8, "high": 0.5}
BUMP_FLOOR_G = min(BUMP_THRESHOLDS_G.values())

_EPS = 1e-9


@dataclass(frozen=True)
class Decomposition:
    """Raw (unsmoothed) gravity-free acceleration in g, split along the travel direction."""

    t: np.ndarray
    longitudinal: np.ndarray  # + accelerating, - braking
    lateral: np.ndarray  # + right
    vertical: np.ndarray  # world z component


@dataclass(frozen=True)
class BumpEvent:
    t: float
    peak_g: float


def linear_accel_camera(accel: np.ndarray, quat: np.ndarray) -> np.ndarray:
    """(N, 3) acceleration in camera axes with gravity removed."""
    return np.asarray(accel, dtype=float) - gravity_in_camera(quat)


def linear_accel_world(accel: np.ndarray, quat: np.ndarray) -> np.ndarray:
    """(N, 3) gravity-free acceleration in the world frame."""
    r = rotation_matrices(quat)
    return np.einsum("nij,nj->ni", r, linear_accel_camera(accel, quat))


def _rate_limit(angle: np.ndarray, t: np.ndarray, max_rate_deg_s: float) -> np.ndarray:
    """Causal slew-rate limit: the output follows the input at no more than `max_rate_deg_s`."""
    out = np.empty_like(angle)
    if len(angle) == 0:
        return out
    out[0] = angle[0]
    step = np.radians(max_rate_deg_s) * np.diff(t)
    for i in range(1, len(angle)):
        d = angle[i] - out[i - 1]
        s = step[i - 1]
        out[i] = out[i - 1] + min(max(d, -s), s)
    return out


def travel_direction(quat: np.ndarray, t: np.ndarray, mount: Mount = "bike") -> np.ndarray:
    """(N, 2) unit horizontal vectors (world x, y) of the travel direction.

    The raw direction is the camera's viewing axis projected onto the horizontal plane. For the
    helmet mount its angle is rate-limited first, so a head turn cannot swing the vector faster
    than HELMET_TURN_RATE_LIMIT_DEG_S. The vector (not the angle) is then smoothed with a centred
    window, so there is no wrap-around at 180 degrees.
    """
    r = rotation_matrices(quat)
    fwd = r[:, :2, VIEW_AXIS]
    norm = np.linalg.norm(fwd, axis=1)
    if len(norm) == 0:
        return np.zeros((0, 2))
    # Looking straight up or down leaves no horizontal heading. Hold the last usable one.
    usable = norm > 1e-3
    if not usable.any():
        return np.tile([1.0, 0.0], (len(norm), 1))
    idx = np.where(usable, np.arange(len(norm)), 0)
    np.maximum.accumulate(idx, out=idx)
    first = int(np.argmax(usable))
    idx[: first + 1] = first
    unit = fwd[idx] / norm[idx, None]

    if mount == "helmet":
        psi = np.unwrap(np.arctan2(unit[:, 1], unit[:, 0]))
        psi = _rate_limit(psi, t, HELMET_TURN_RATE_LIMIT_DEG_S)
        unit = np.stack([np.cos(psi), np.sin(psi)], axis=1)

    smooth = lowpass(unit, t, TRAVEL_SMOOTH_S[mount])
    return smooth / np.maximum(np.linalg.norm(smooth, axis=1, keepdims=True), _EPS)


def decompose(t: np.ndarray, quat: np.ndarray, accel: np.ndarray, mount: Mount = "bike") -> Decomposition:
    """Split the gravity-free acceleration into longitudinal, lateral and vertical components."""
    a = linear_accel_world(accel, quat)
    f = travel_direction(quat, t, mount)
    longitudinal = a[:, 0] * f[:, 0] + a[:, 1] * f[:, 1]
    # Right of the heading is (-f_y, f_x): the world frame is z-down.
    lateral = a[:, 1] * f[:, 0] - a[:, 0] * f[:, 1]
    return Decomposition(np.asarray(t, dtype=float), longitudinal, lateral, a[:, 2])


def decompose_samples(samples: Samples, mount: Mount = "bike") -> Decomposition:
    return decompose(samples.t, samples.quat, samples.accel, mount)


def meter_components(d: Decomposition) -> tuple[np.ndarray, np.ndarray]:
    """Longitudinal and lateral in g, low-passed for the meter with a 0.4 s Hann window."""
    return (
        hann_smooth(d.longitudinal, d.t, METER_SMOOTH_S),
        hann_smooth(d.lateral, d.t, METER_SMOOTH_S),
    )


def bump_residual(vertical: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Magnitude of the vertical acceleration after removing the 1 s centred moving average."""
    return np.abs(vertical - lowpass(vertical, t, BUMP_TREND_S))


def _local_maxima(values: np.ndarray, floor: float) -> np.ndarray:
    v = values
    inner = np.flatnonzero((v[1:-1] >= v[:-2]) & (v[1:-1] > v[2:]) & (v[1:-1] >= floor)) + 1
    return inner


def bump_candidates(t: np.ndarray, vertical: np.ndarray) -> list[BumpEvent]:
    """Peaks of the residual at the lowest threshold, one per BUMP_MERGE_S window (largest kept).

    Every sensitivity is a threshold on this one list, so a higher sensitivity can only add events.
    Greedy suppression in order of descending peak gives the same result as merging at any
    threshold and then filtering, which is what makes the subset property hold by construction.
    """
    t = np.asarray(t, dtype=float)
    if len(t) < 3:
        return []
    res = bump_residual(np.asarray(vertical, dtype=float), t)
    peaks = _local_maxima(res, BUMP_FLOOR_G)
    order = peaks[np.argsort(-res[peaks], kind="stable")]
    accepted_t: list[float] = []
    accepted: list[BumpEvent] = []
    for i in order:
        ti = float(t[i])
        j = bisect_left(accepted_t, ti)
        near = (j < len(accepted_t) and accepted_t[j] - ti < BUMP_MERGE_S) or (
            j > 0 and ti - accepted_t[j - 1] < BUMP_MERGE_S
        )
        if near:
            continue
        insort(accepted_t, ti)
        accepted.append(BumpEvent(ti, float(res[i])))
    return sorted(accepted, key=lambda e: e.t)


def filter_bumps(candidates: list[BumpEvent], sensitivity: str) -> list[BumpEvent]:
    threshold = BUMP_THRESHOLDS_G[sensitivity]
    return [e for e in candidates if e.peak_g >= threshold]


def bump_events(t: np.ndarray, vertical: np.ndarray, sensitivity: str = "medium") -> list[BumpEvent]:
    """Bump events for one sensitivity level, sorted by time."""
    if sensitivity not in BUMP_THRESHOLDS_G:
        raise ValueError(f"unknown sensitivity {sensitivity!r}")
    return filter_bumps(bump_candidates(t, vertical), sensitivity)
