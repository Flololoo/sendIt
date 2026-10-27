"""Telemetry data model: per-sample arrays, clip metadata and time-based lookup."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class Metadata:
    source: str
    telemetry_available: bool
    proto_schema: str | None
    model: str | None
    serial: str | None
    firmware: str | None
    width: int
    height: int
    fps: float | None
    rotation: int
    display_width: int
    display_height: int
    orientation: str  # "portrait" or "landscape"
    duration_s: float
    start_utc: str | None  # ISO 8601 with UTC offset
    has_gps: bool

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Metadata":
        return cls(**data)


@dataclass(frozen=True)
class Samples:
    t: np.ndarray  # (N,) seconds from the start of the video
    quat: np.ndarray  # (N, 4) orientation, unit quaternion (w, x, y, z)
    accel: np.ndarray  # (N, 3) acceleration in g
    iso: np.ndarray  # (N,)
    shutter_s: np.ndarray  # (N,) exposure time in seconds
    wb_k: np.ndarray  # (N,) white balance in Kelvin

    def __len__(self) -> int:
        return len(self.t)

    @classmethod
    def empty(cls) -> "Samples":
        return cls(
            t=np.zeros(0),
            quat=np.zeros((0, 4)),
            accel=np.zeros((0, 3)),
            iso=np.zeros(0),
            shutter_s=np.zeros(0),
            wb_k=np.zeros(0),
        )


@dataclass(frozen=True)
class Sample:
    t: float
    quat: np.ndarray
    accel: np.ndarray
    iso: float
    shutter_s: float
    wb_k: float


def slerp(q0: np.ndarray, q1: np.ndarray, a: float) -> np.ndarray:
    """Spherical interpolation between two unit quaternions along the shorter arc."""
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1 = -q1
        dot = -dot
    if dot > 0.9995:
        # Nearly identical: linear interpolation is accurate and avoids division by ~0.
        q = (1.0 - a) * q0 + a * q1
        return q / np.linalg.norm(q)
    theta = np.arccos(min(dot, 1.0)) * a
    perp = q1 - q0 * dot
    perp /= np.linalg.norm(perp)
    return q0 * np.cos(theta) + perp * np.sin(theta)


@dataclass(frozen=True)
class Telemetry:
    samples: Samples
    meta: Metadata
    skipped: int = 0  # records that could not be decoded

    def __len__(self) -> int:
        return len(self.samples)

    def at(self, t: float) -> Sample:
        """Return the telemetry at time t (seconds).

        Orientation is slerped and acceleration lerped between the two neighbouring
        records. Exposure values (ISO, shutter, WB) are not interpolated; they take the
        value of the record at or before t. Times outside the clip clamp to the first
        or last record.
        """
        s = self.samples
        n = len(s)
        if n == 0:
            raise ValueError("no telemetry samples available for this clip")
        ts = s.t
        if t <= ts[0]:
            i = j = 0
            a = 0.0
        elif t >= ts[-1]:
            i = j = n - 1
            a = 0.0
        else:
            j = int(np.searchsorted(ts, t, side="right"))
            i = j - 1
            span = ts[j] - ts[i]
            a = float((t - ts[i]) / span) if span > 0 else 0.0

        if a == 0.0:
            quat = s.quat[i].copy()
            accel = s.accel[i].copy()
        else:
            quat = slerp(s.quat[i], s.quat[j], a)
            accel = (1.0 - a) * s.accel[i] + a * s.accel[j]
        return Sample(
            t=float(t),
            quat=quat,
            accel=accel,
            iso=float(s.iso[i]),
            shutter_s=float(s.shutter_s[i]),
            wb_k=float(s.wb_k[i]),
        )
