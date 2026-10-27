"""Helpers for the web and workspace tests: tiny generated clips and waiting for background jobs."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from app.workspace import Workspace


def make_clip(path: Path, seconds: float = 2.0, size: str = "320x240") -> Path:
    """Write a tiny H.264 MP4 with ffmpeg's test pattern. It has no DJI telemetry track."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30",
            "-t", str(seconds), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
            "-f", "mp4", str(path),
        ],
        check=True,
    )
    return path


def drain(workspace: Workspace, timeout: float = 120.0) -> None:
    """Wait until every background job (telemetry, thumbnail, proxy) has finished."""
    workspace.jobs.wait_idle(timeout)


def wait_for(predicate, timeout: float = 120.0, interval: float = 0.2):
    """Poll `predicate` until it returns a truthy value and return that value."""
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(interval)
