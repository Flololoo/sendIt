"""Thin wrappers around the ffmpeg and ffprobe command-line tools.

Only the data stream is read: packet timing comes from ffprobe and the raw
payload from ffmpeg with stream copy, so the 10+ GB video is never decoded.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np

REQUIRED_TOOLS = ("ffmpeg", "ffprobe")
TELEMETRY_HANDLER = "DJI meta"
TELEMETRY_CODEC_TAG = "djmd"


class MissingToolError(RuntimeError):
    """Raised when ffmpeg or ffprobe is not available on PATH."""


class ToolError(RuntimeError):
    """Raised when ffmpeg or ffprobe exits with an error."""


def require_ffmpeg() -> None:
    """Raise MissingToolError with install guidance if a required tool is missing."""
    missing = [name for name in REQUIRED_TOOLS if shutil.which(name) is None]
    if missing:
        raise MissingToolError(
            f"Required tool(s) not found on PATH: {', '.join(missing)}. "
            "Install FFmpeg (e.g. `winget install Gyan.FFmpeg`), open a new terminal "
            "so PATH is refreshed, and check with `ffmpeg -version` and `ffprobe -version`."
        )


def _run(cmd: list[str]) -> bytes:
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, check=False)
    if result.returncode != 0:
        raise ToolError(f"{cmd[0]} failed ({result.returncode}): {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def probe(path: str | Path) -> dict:
    """Return ffprobe's format and stream description for a file."""
    out = _run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    return json.loads(out)


def find_telemetry_stream(info: dict) -> int | None:
    """Return the index of the DJI meta data stream, or None if the file has none."""
    for stream in info.get("streams", []):
        if stream.get("codec_type") != "data":
            continue
        handler = stream.get("tags", {}).get("handler_name")
        if handler == TELEMETRY_HANDLER or stream.get("codec_tag_string") == TELEMETRY_CODEC_TAG:
            return int(stream["index"])
    return None


def _parse_rate(text: str | None) -> float | None:
    if not text or text in ("0/0", "N/A"):
        return None
    value = float(Fraction(text))
    return value if value > 0 else None


def video_summary(info: dict) -> dict:
    """Summarise the main video stream: size, rotation, rate, duration and start time."""
    video = next(
        (
            s
            for s in info.get("streams", [])
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    if video is None:
        raise ToolError("no video stream found")
    rotation = 0
    for side in video.get("side_data_list", []):
        if "rotation" in side:
            rotation = int(side["rotation"])
    fmt = info.get("format", {})
    tags = {**video.get("tags", {}), **fmt.get("tags", {})}
    nb_frames = video.get("nb_frames")
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "rotation": rotation,
        "fps": _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate")),
        "duration_s": float(video.get("duration") or fmt.get("duration") or 0.0),
        "start_time_s": float(video.get("start_time") or 0.0),
        "nb_frames": int(nb_frames) if nb_frames not in (None, "N/A") else None,
        "creation_time": tags.get("creation_time"),
    }


def read_packet_times_and_sizes(path: str | Path, index: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (pts_time seconds, size bytes) for every packet of one stream, in file order."""
    out = _run(
        [
            "ffprobe", "-v", "error", "-select_streams", str(index),
            "-show_entries", "packet=pts_time,size", "-of", "json", str(path),
        ]
    )
    packets = json.loads(out).get("packets", [])
    pts = np.array([float(p["pts_time"]) for p in packets], dtype=np.float64)
    sizes = np.array([int(p["size"]) for p in packets], dtype=np.int64)
    return pts, sizes


def read_raw_packets(path: str | Path, index: int) -> bytes:
    """Return the concatenated payload of one data stream, packets back to back."""
    return _run(
        [
            "ffmpeg", "-v", "error", "-i", str(path),
            "-map", f"0:{index}", "-c", "copy", "-f", "data", "-",
        ]
    )
