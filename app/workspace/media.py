"""ffmpeg work for the library: probing an upload, cover thumbnails and 720p H.264 proxies.

Probing and metadata reuse the telemetry engine. Nothing here touches the database.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from app.telemetry import ffmpeg_io
from app.telemetry.extract import build_metadata
from app.telemetry.model import Metadata

THUMB_SHORT_SIDE = 240
PROXY_SHORT_SIDE = 720
PROXY_BITRATE_ARGS = ("-c:v", "libx264", "-preset", "veryfast", "-crf", "23")


def probe_metadata(path: Path) -> Metadata:
    """Return clip metadata from ffprobe alone. Raises ToolError or ValueError if the file is not readable video."""
    ffmpeg_io.require_ffmpeg()
    summary = ffmpeg_io.video_summary(ffmpeg_io.probe(path))
    return build_metadata(summary, {}, source=path.name, telemetry_available=False, has_gps=False)


def _short_side_filter(meta: Metadata, short_side: int) -> str:
    """Scale so the shorter side of the upright picture is `short_side` pixels (ffmpeg autorotates the input)."""
    if meta.display_height >= meta.display_width:
        return f"scale={short_side}:-2"
    return f"scale=-2:{short_side}"


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *args], stdin=subprocess.DEVNULL, capture_output=True, check=False
    )
    if result.returncode != 0:
        reason = result.stderr.decode(errors="replace").strip().splitlines()
        raise ffmpeg_io.ToolError(f"ffmpeg failed: {reason[-1] if reason else 'no error message'}")


def make_thumbnail(source: Path, out: Path, meta: Metadata) -> None:
    """Write a JPEG to `out`: the embedded cover stream if the file has one, else the first frame."""
    ffmpeg_io.require_ffmpeg()
    part = out.with_name(out.stem + ".part.jpg")
    try:
        _run_ffmpeg(["-i", str(source), "-map", "0:v:1", "-frames:v", "1", str(part)])
    except ffmpeg_io.ToolError:
        # No cover stream, which is the usual case for clips the camera did not write a cover into.
        part.unlink(missing_ok=True)
        _run_ffmpeg([
            "-i", str(source), "-map", "0:v:0", "-frames:v", "1",
            "-vf", _short_side_filter(meta, THUMB_SHORT_SIDE), str(part),
        ])
    os.replace(part, out)


def make_proxy(
    source: Path,
    out: Path,
    meta: Metadata,
    *,
    progress: Callable[[float], None],
    should_cancel: Callable[[], bool],
) -> bool:
    """Transcode `source` to a 720p H.264 MP4 at `out`. Returns False if cancelled, leaving no file behind."""
    ffmpeg_io.require_ffmpeg()
    part = out.with_name(out.stem + ".part.mp4")
    duration = meta.duration_s or 0.0
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-nostats", "-progress", "pipe:1",
        "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
        "-vf", _short_side_filter(meta, PROXY_SHORT_SIDE), *PROXY_BITRATE_ARGS,
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-f", "mp4", str(part),
    ]
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err)
        completed = False
        try:
            for raw in proc.stdout:
                if should_cancel():
                    break
                key, _, value = raw.decode(errors="replace").strip().partition("=")
                if key == "out_time_us" and value.isdigit() and duration > 0:
                    progress(min(int(value) / 1e6 / duration, 1.0))
            else:
                completed = True
        finally:
            if not completed:
                proc.kill()  # cancelled, or an error while reading progress
            rc = proc.wait()
        if not completed:
            part.unlink(missing_ok=True)
            return False
        if rc != 0:
            err.seek(0)
            lines = err.read().decode(errors="replace").strip().splitlines()
            part.unlink(missing_ok=True)
            raise ffmpeg_io.ToolError(f"ffmpeg failed: {lines[-1] if lines else 'no error message'}")
    os.replace(part, out)
    return True
