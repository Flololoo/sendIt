"""Lean angle signal: gravity in the camera frame, roll about the viewing axis, calibration, smoothing.

The camera's fused quaternion is turned into the direction of gravity as the camera sees it.
Roll is the angle of that direction inside the sensor plane, relative to an upright reference
found automatically from straight riding. No Euler angles are used, so the portrait mount
(about 90 degrees) causes no gimbal trouble.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.telemetry import Telemetry

from .contract import Mount

LEAN_LIMIT_DEG = 65.0
STRAIGHT_RATE_DEG_S = 2.0  # |heading rate| below this counts as straight
STRAIGHT_MIN_RUN_S = 3.0
STRAIGHT_MIN_TOTAL_S = 10.0
SMOOTHING_WINDOW_S: dict[str, float] = {"bike": 0.25, "helmet": 0.8}
CONVENTION_LOWPASS_S = 2.0

# Camera axes in the DJI sensor frame, found on clip 0051: x looks forward, y is down in the
# portrait mount, z points sideways. Roll is measured in the (y, z) plane.
VIEW_AXIS = 0
DOWN_AXIS = 1
SIDE_AXIS = 2

# Sign of roll that makes leaning right positive. Pinned against the footage (see tests).
ROLL_SIGN = 1.0


@dataclass(frozen=True)
class Convention:
    """How to read the quaternion: component order, direction of the rotation, and gravity sign."""

    order: str  # "wxyz" or "xyzw"
    inverse: bool  # True if the quaternion maps world to camera
    sign: int  # +1 if the accelerometer reads "up", -1 if it reads "down"


CANDIDATES: tuple[Convention, ...] = tuple(
    Convention(order, inverse, sign)
    for order in ("wxyz", "xyzw")
    for inverse in (False, True)
    for sign in (1, -1)
)

# Chosen by `select_convention` on clip 0051 (mean error 0.5 degrees): the accelerometer reads
# the direction of gravity, and the quaternion rotates camera to world, so gravity in the camera
# frame is the world "down" axis rotated by the inverse.
CONVENTION = Convention(order="wxyz", inverse=True, sign=-1)


def rotation_matrices(quat: np.ndarray, order: str = "wxyz") -> np.ndarray:
    """Return (N, 3, 3) rotation matrices for (N, 4) quaternions. They are normalised first."""
    q = np.asarray(quat, dtype=float)
    if order == "xyzw":
        q = q[:, [3, 0, 1, 2]]
    elif order != "wxyz":
        raise ValueError(f"unknown quaternion order {order!r}")
    q = q / np.linalg.norm(q, axis=1, keepdims=True)
    w, x, y, z = q.T
    return np.stack(
        [
            1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
            2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
            2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y),
        ],
        axis=-1,
    ).reshape(-1, 3, 3)


def gravity_in_camera(quat: np.ndarray, convention: Convention = CONVENTION) -> np.ndarray:
    """Return (N, 3) unit vectors: the direction an accelerometer at rest would read, in camera axes."""
    r = rotation_matrices(quat, convention.order)
    up = np.array([0.0, 0.0, 1.0])
    g = np.einsum("nji,j->ni", r, up) if convention.inverse else r @ up
    return convention.sign * g


def lowpass(values: np.ndarray, t: np.ndarray, window_s: float) -> np.ndarray:
    """Centred moving average along axis 0 with edge padding, so the output has no time lag."""
    n = max(1, int(round(window_s * _sample_rate(t))))
    if n <= 1 or len(values) < 2:
        return np.asarray(values, dtype=float)
    pad_lo, pad_hi = n // 2, n - 1 - n // 2
    kernel = np.ones(n) / n
    v = np.asarray(values, dtype=float)
    cols = v.reshape(len(v), -1)
    out = np.empty_like(cols)
    for j in range(cols.shape[1]):
        out[:, j] = np.convolve(np.pad(cols[:, j], (pad_lo, pad_hi), mode="edge"), kernel, mode="valid")
    return out.reshape(v.shape)


def select_convention(
    quat: np.ndarray, accel: np.ndarray, t: np.ndarray
) -> tuple[Convention, float]:
    """Return the candidate whose gravity best matches the low-passed accelerometer, and its mean error in degrees."""
    ref = lowpass(accel, t, CONVENTION_LOWPASS_S)
    ref = ref / np.linalg.norm(ref, axis=1, keepdims=True)
    best: tuple[Convention, float] | None = None
    for conv in CANDIDATES:
        cos = np.clip((gravity_in_camera(quat, conv) * ref).sum(axis=1), -1.0, 1.0)
        err = float(np.degrees(np.arccos(cos)).mean())
        if best is None or err < best[1]:
            best = (conv, err)
    assert best is not None
    return best


def roll_deg(g_cam: np.ndarray) -> np.ndarray:
    """Roll of gravity inside the sensor plane in degrees, 0 when the down axis points down."""
    return ROLL_SIGN * np.degrees(np.arctan2(g_cam[:, SIDE_AXIS], -g_cam[:, DOWN_AXIS]))


def heading_rate_deg_s(quat: np.ndarray, t: np.ndarray, convention: Convention = CONVENTION) -> np.ndarray:
    """Rate of change of the viewing direction's compass heading, in degrees per second."""
    r = rotation_matrices(quat, convention.order)
    # With `inverse` the matrix maps camera to world, so the viewing axis is a column of it.
    fwd = r[:, :, VIEW_AXIS] if convention.inverse else r[:, VIEW_AXIS, :]
    yaw = np.unwrap(np.arctan2(fwd[:, 1], fwd[:, 0]))
    return np.degrees(np.gradient(yaw, t))


def wrap_deg(angle):
    """Wrap angles (scalar or array) to [-180, 180)."""
    return (angle + 180.0) % 360.0 - 180.0


def circular_median_deg(angles: np.ndarray) -> float:
    """Median of angles on a circle: the median of their offsets from the circular mean."""
    rad = np.radians(angles)
    centre = np.degrees(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean()))
    return float(centre + np.median(wrap_deg(angles - centre)))


def straight_mask(rate_deg_s: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Samples inside runs of at least STRAIGHT_MIN_RUN_S where the heading rate is below the limit."""
    rate = lowpass(rate_deg_s, t, 0.5)
    low = np.abs(rate) < STRAIGHT_RATE_DEG_S
    mask = np.zeros(len(low), dtype=bool)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], low.astype(int), [0]))))
    for start, stop in zip(edges[::2], edges[1::2]):
        if t[stop - 1] - t[start] >= STRAIGHT_MIN_RUN_S:
            mask[start:stop] = True
    return mask


def upright_reference(roll: np.ndarray, rate_deg_s: np.ndarray, t: np.ndarray) -> float:
    """Roll that counts as upright: circular median over straight riding, or over everything if there is little."""
    mask = straight_mask(rate_deg_s, t)
    if mask.sum() * _sample_period(t) < STRAIGHT_MIN_TOTAL_S:
        return circular_median_deg(roll)
    return circular_median_deg(roll[mask])


def hann_smooth(values: np.ndarray, t: np.ndarray, window_s: float) -> np.ndarray:
    """Zero-phase smoothing with a centred Hann window of `window_s` seconds."""
    n = int(round(window_s * _sample_rate(t)))
    if n < 3:
        return np.asarray(values, dtype=float)
    n += 1 - n % 2  # odd length keeps the window centred on a sample
    kernel = np.hanning(n + 2)[1:-1]
    kernel /= kernel.sum()
    padded = np.pad(values, (n // 2, n // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def lean_from_roll(
    roll: np.ndarray,
    rate_deg_s: np.ndarray,
    t: np.ndarray,
    mount: Mount = "bike",
    offset: float = 0.0,
) -> np.ndarray:
    """Turn a roll series into the displayed lean series: reference, smoothing, offset, clamp."""
    reference = upright_reference(roll, rate_deg_s, t)
    rel = wrap_deg(roll - reference)
    smooth = hann_smooth(rel, t, SMOOTHING_WINDOW_S[mount])
    return np.clip(smooth + offset, -LEAN_LIMIT_DEG, LEAN_LIMIT_DEG)


def lean_series(telemetry: Telemetry, mount: Mount = "bike", offset: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Return (t, lean in degrees) for a whole clip. Right is positive."""
    s = telemetry.samples
    roll = roll_deg(gravity_in_camera(s.quat))
    rate = heading_rate_deg_s(s.quat, s.t)
    return s.t, lean_from_roll(roll, rate, s.t, mount, offset)


def _sample_period(t: np.ndarray) -> float:
    return float(np.median(np.diff(t))) if len(t) > 1 else 1.0


def _sample_rate(t: np.ndarray) -> float:
    return 1.0 / _sample_period(t)
