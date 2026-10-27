"""CSV export of a clip's telemetry, one row per sample."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from .cache import get_telemetry
from .model import Telemetry

COLUMNS = ("t_s", "qw", "qx", "qy", "qz", "ax_g", "ay_g", "az_g", "iso", "shutter_s", "wb_k")


def export_csv(source: str | Path | Telemetry, out: str | Path) -> int:
    """Write telemetry to a CSV file and return the number of data rows.

    `source` is a video path (loaded through the cache) or an already loaded Telemetry.
    """
    telemetry = source if isinstance(source, Telemetry) else get_telemetry(source)
    s = telemetry.samples
    rows = np.column_stack([s.t, s.quat, s.accel, s.iso, s.shutter_s, s.wb_k])
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        writer.writerows(rows.tolist())
    return len(s)
