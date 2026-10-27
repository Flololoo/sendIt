"""Export: renders a clip with the enabled overlays burned in, to an MP4 in the exports folder.

Pass 1 draws the overlay layer frame by frame and pipes it to ffmpeg, which writes a
lossless alpha .mov into a temporary folder. Pass 2 decodes the source, scales it to the
preset, composites the layer and encodes the result. Both ffmpeg runs report progress
through `-progress pipe:1`, and the caller can cancel and receive every process handle.
"""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from fractions import Fraction
from pathlib import Path
from typing import IO, Any, Literal

from app.overlays.config import ConfigError, validate_config
from app.overlays.contract import Mount
from app.overlays.layer import LayerItem, plan_layer, render_layer, union_box
from app.overlays.registry import OverlayRegistry, default_registry
from app.telemetry.cache import DEFAULT_CACHE_ROOT
from app.telemetry.ffmpeg_io import MissingToolError, ToolError, require_ffmpeg

from .clip import load_clip
from .encoders import ENCODER_ARGS, EncoderError, is_hevc, startup_encoder
from .naming import DEFAULT_EXPORTS_DIR, export_stem, reserve_output

log = logging.getLogger(__name__)

Preset = Literal["original", "social"]
PRESETS: tuple[str, ...] = ("original", "social")
SOCIAL_PORTRAIT = (1080, 1920)
SOCIAL_LANDSCAPE = (1920, 1080)
PASS1_SHARE = 0.15  # share of the reported progress that pass 1 accounts for
AUDIO_BITRATE = "192k"
END_TOLERANCE = 1e-3  # seconds
DISK_FULL_MARKERS = ("No space left on device", "Errno 28", "ENOSPC")


class ExportError(RuntimeError):
    """The export was rejected or failed. The message says why."""


class ExportCancelled(RuntimeError):
    """The export was cancelled. Its processes were stopped and its files removed."""


class _Run:
    """One export's ffmpeg processes and callbacks. Every process is registered here."""

    def __init__(
        self,
        progress: Callable[[float], None] | None,
        should_cancel: Callable[[], bool],
        on_process: Callable[[subprocess.Popen], None] | None,
    ) -> None:
        self.progress = progress
        self.should_cancel = should_cancel
        self.on_process = on_process
        self.processes: list[subprocess.Popen] = []
        self._last = 0.0

    def report(self, fraction: float) -> None:
        """Report overall progress; values never go backwards and are capped at 1.0."""
        self._last = min(max(fraction, self._last), 1.0)
        if self.progress is not None:
            self.progress(self._last)

    def check_cancel(self) -> None:
        if self.should_cancel():
            raise ExportCancelled("export cancelled")

    def start(self, cmd: list[str], stdin: Any, stdout: Any, stderr: IO[bytes]) -> subprocess.Popen:
        proc = subprocess.Popen(cmd, stdin=stdin, stdout=stdout, stderr=stderr)
        self.processes.append(proc)
        if self.on_process is not None:
            self.on_process(proc)
        return proc

    def kill_all(self) -> None:
        for proc in self.processes:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def resolve_range(start: float | None, end: float | None, duration: float) -> tuple[float, float]:
    """Return the (start, end) range in seconds, with defaults filled in. Raises ExportError if invalid."""
    start_s = 0.0 if start is None else float(start)
    end_s = duration if end is None else float(end)
    if not (math.isfinite(start_s) and math.isfinite(end_s)):
        raise ExportError(f"start and end must be finite numbers, got start={start_s} and end={end_s}")
    if start_s < 0:
        raise ExportError(f"start {start_s:g} s is before the beginning of the clip")
    if end_s > duration + END_TOLERANCE:
        raise ExportError(f"end {end_s:g} s is after the end of the clip ({duration:.3f} s)")
    if start_s >= end_s:
        raise ExportError(f"start ({start_s:g} s) must be before end ({end_s:g} s)")
    return start_s, min(end_s, duration)


def output_size(meta: Any, preset: str) -> tuple[int, int]:
    """Return the output frame size (width, height) for a preset."""
    if preset == "original":
        return meta.display_width, meta.display_height
    if preset == "social":
        return SOCIAL_PORTRAIT if meta.display_height >= meta.display_width else SOCIAL_LANDSCAPE
    raise ExportError(f"unknown preset {preset!r}, expected one of {list(PRESETS)}")


def write_overlay_layer(
    items: list[LayerItem],
    start: float,
    fps: Fraction,
    count: int,
    path: Path,
    run: _Run | None = None,
) -> None:
    """Pass 1: write `count` frames of the overlay layer to a lossless alpha .mov at `path`.

    Frame i is drawn at source time start + i / fps. Progress covers PASS1_SHARE of the total.
    """
    run = run or _Run(None, lambda: False, None)
    x0, y0, x1, y1 = union_box(items)
    cmd = [
        "ffmpeg", "-hide_banner", "-v", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{x1 - x0}x{y1 - y0}",
        "-framerate", str(fps), "-i", "-",
        "-c:v", "qtrle", "-pix_fmt", "rgba", str(path),
    ]
    with tempfile.TemporaryFile() as err:
        proc = run.start(cmd, subprocess.PIPE, subprocess.DEVNULL, err)
        try:
            for i in range(count):
                run.check_cancel()
                layer = render_layer(items, start + i / float(fps))
                try:
                    proc.stdin.write(layer.tobytes())
                except OSError:
                    break  # ffmpeg stopped reading early; its exit code and stderr explain why
                run.report(PASS1_SHARE * (i + 1) / count)
        except BaseException:
            proc.kill()  # a drawing error or cancel: stop ffmpeg before the error propagates
            proc.wait()
            raise
        finally:
            _close_quietly(proc.stdin)
        rc = proc.wait()
        if rc != 0:
            raise ExportError(_explain(_read(err), "writing the overlay layer"))


def _pass2_cmd(
    source: Path,
    start: float,
    duration: float,
    layer_mov: Path,
    xy: tuple[int, int],
    size: tuple[int, int],
    encoder: str,
    hwaccel: bool,
    out_path: Path,
) -> list[str]:
    out_w, out_h = size
    x, y = xy
    graph = (
        f"[0:v]scale={out_w}:{out_h},setsar=1,format=yuv420p[base];"
        f"[base][1:v]overlay=x={x}:y={y}:eof_action=pass[v]"
    )
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-progress", "pipe:1", "-nostats"]
    if hwaccel:
        cmd += ["-hwaccel", "cuda"]
    # hvc1 is the HEVC tag QuickTime, iOS and Instagram accept; ffmpeg defaults to hev1.
    hevc_tag = ["-tag:v", "hvc1"] if is_hevc(encoder) else []
    return [
        *cmd,
        "-ss", f"{start:.6f}", "-i", str(source), "-i", str(layer_mov),
        "-filter_complex", graph,
        "-map", "[v]", "-map", "0:a?",
        *ENCODER_ARGS[encoder], *hevc_tag, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-t", f"{duration:.6f}", "-movflags", "+faststart", "-f", "mp4", str(out_path),
    ]


def _run_pass2(run: _Run, cmd: list[str], duration: float) -> tuple[bool, bool, str]:
    """Run one pass 2 attempt. Returns (succeeded, progress_seen, stderr text)."""
    with tempfile.TemporaryFile() as err:
        proc = run.start(cmd, subprocess.DEVNULL, subprocess.PIPE, err)
        seen = False
        for raw in proc.stdout:
            run.check_cancel()
            key, _, value = raw.decode(errors="replace").strip().partition("=")
            if key == "out_time_us" and value.isdigit():
                seen = True
                done = min(int(value) / 1e6 / duration, 1.0)
                run.report(PASS1_SHARE + (1 - PASS1_SHARE) * done)
        rc = proc.wait()
        return rc == 0, seen, _read(err)


def _composite(
    run: _Run,
    source: Path,
    rng: tuple[float, float],
    layer_mov: Path,
    xy: tuple[int, int],
    size: tuple[int, int],
    encoder: str,
    out_path: Path,
) -> None:
    """Pass 2 with fallbacks: CUDA decode, then software decode, then libx264.

    A failed attempt moves on to the next option only if it failed before reporting any progress.
    """
    start, end = rng
    duration = end - start
    attempts = [(True, encoder), (False, encoder)]
    if encoder != "libx264":
        attempts.append((False, "libx264"))
    text = ""
    for hwaccel, enc in attempts:
        cmd = _pass2_cmd(source, start, duration, layer_mov, xy, size, enc, hwaccel, out_path)
        ok, seen, text = _run_pass2(run, cmd, duration)
        if ok:
            return
        if seen:
            break
        run.check_cancel()
        log.warning("export attempt failed (hwaccel=%s, encoder=%s), trying the next option", hwaccel, enc)
    raise ExportError(_explain(text, "encoding the export"))


def _frame_rate(fps: float | None) -> Fraction:
    if not fps:
        raise ExportError("the source has no usable frame rate")
    return Fraction(fps).limit_denominator(1001)


def _read(err: IO[bytes]) -> str:
    err.seek(0)
    return err.read().decode(errors="replace")


def _explain(text: str, stage: str) -> str:
    """Turn ffmpeg's stderr into a short reason that names the cause."""
    if any(marker in text for marker in DISK_FULL_MARKERS):
        return f"insufficient disk space while {stage}"
    if "Invalid data found" in text or "No such file" in text:
        return f"the source clip could not be read while {stage}"
    lines = [line for line in text.splitlines() if line.strip()]
    return f"ffmpeg failed while {stage}: {lines[-1] if lines else 'no error message'}"


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _close_quietly(stream: IO[bytes] | None) -> None:
    """Close ffmpeg's stdin so it sees end of input. A broken pipe here is reported by its exit code."""
    if stream is None:
        return
    try:
        stream.close()
    except OSError:
        pass


def export(
    clip: str | Path,
    config: Mapping[str, Any],
    *,
    preset: Preset = "original",
    start: float | None = None,
    end: float | None = None,
    mount: Mount = "bike",
    exports_dir: Path = DEFAULT_EXPORTS_DIR,
    registry: OverlayRegistry = default_registry,
    encoder: str | None = None,
    progress: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] = lambda: False,
    on_process: Callable[[subprocess.Popen], None] | None = None,
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> Path:
    """Render `clip` with the overlays in `config` burned in, and return the new MP4's path.

    Everything is validated before rendering starts. `progress` receives fractions from 0 to 1.
    `should_cancel` is polled while rendering; when it returns True the export is stopped and
    ExportCancelled is raised. `on_process` receives each ffmpeg Popen as it starts. On any
    failure or cancel, the processes are stopped and the partial output is deleted.
    """
    try:
        require_ffmpeg()
    except MissingToolError as exc:
        raise ExportError(str(exc)) from exc
    if preset not in PRESETS:
        raise ExportError(f"unknown preset {preset!r}, expected one of {list(PRESETS)}")
    try:
        configs = validate_config(config, registry)
    except ConfigError as exc:
        raise ExportError("invalid overlay configuration: " + "; ".join(exc.errors)) from exc
    enabled = [c for c in configs.values() if c.enabled]
    if not enabled:
        raise ExportError("no overlay is enabled, so there is nothing to export")

    try:
        ctx = load_clip(clip, mount, cache_root=cache_root)
    except (ToolError, OSError, ValueError) as exc:
        raise ExportError(f"the source clip could not be read: {Path(clip).name}: {exc}") from exc
    for c in enabled:
        availability = registry.availability(c.overlay, ctx)
        if not availability.available:
            raise ExportError(f"overlay {c.overlay.id!r} is unavailable for this clip: {availability.reason}")

    rng = resolve_range(start, end, ctx.meta.duration_s)
    size = output_size(ctx.meta, preset)
    fps = _frame_rate(ctx.meta.fps)
    count = round((rng[1] - rng[0]) * float(fps))
    try:
        items = plan_layer(configs, ctx, rng, *size)
    except ValueError as exc:
        raise ExportError(f"the overlays do not fit the {size[0]}x{size[1]} frame: {exc}") from exc
    try:
        chosen = encoder or startup_encoder()
    except EncoderError as exc:
        raise ExportError(str(exc)) from exc

    source = Path(clip)
    out_path = reserve_output(exports_dir, export_stem(source, [c.overlay.id for c in enabled], *rng))
    run = _Run(progress, should_cancel, on_process)
    tmp = Path(tempfile.mkdtemp(prefix="sisv-export-"))
    log.info("exporting %s to %s with %s (%dx%d, %.3f-%.3f s)", source.name, out_path.name, chosen, *size, *rng)
    try:
        layer_mov = tmp / "overlay.mov"
        write_overlay_layer(items, rng[0], fps, count, layer_mov, run)
        run.check_cancel()
        _composite(run, source, rng, layer_mov, union_box(items)[:2], size, chosen, out_path)
        run.report(1.0)
    except BaseException as exc:
        run.kill_all()  # the file stays locked while ffmpeg writes to it
        _discard(out_path)
        if isinstance(exc, OSError):
            raise ExportError(_explain(str(exc), "writing the export")) from exc
        raise
    finally:
        run.kill_all()
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path
