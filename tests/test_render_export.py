import dataclasses
import importlib
import subprocess
import threading
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from overlay_fixtures import TelemetryOverlay, TimestampOverlay, make_clip

from app.overlays.config import validate_config
from app.overlays.layer import plan_layer, render_layer, union_box
from app.overlays.registry import OverlayRegistry
from app.render.export import (
    ExportCancelled,
    ExportError,
    export,
    output_size,
    resolve_range,
    write_overlay_layer,
)
from app.telemetry import ffmpeg_io

export_mod = importlib.import_module("app.render.export")

CLIP = Path(__file__).resolve().parents[1] / "videos" / "DJI_20261026155823_0051_D.MP4"
requires_clip = pytest.mark.skipif(not CLIP.exists(), reason="needs clip 0051 in videos/")
FPS = Fraction(60000, 1001)


def _registry() -> OverlayRegistry:
    reg = OverlayRegistry()
    reg.register(TimestampOverlay())
    reg.register(TelemetryOverlay())
    return reg


def _video_stream(path: Path) -> dict:
    info = ffmpeg_io.probe(path)
    return next(s for s in info["streams"] if s["codec_type"] == "video")


def _frame_count(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
        capture_output=True, check=True, text=True,
    ).stdout
    return int(out.strip())


def _decode_rgba(path: Path, width: int, height: int) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width, 4)


# Unit tests: no clip needed.


def test_range_defaults_to_whole_clip():
    assert resolve_range(None, None, 60.0) == (0.0, 60.0)


def test_valid_range_is_kept():
    assert resolve_range(300, 330, 600.0) == (300.0, 330.0)


@pytest.mark.parametrize(
    "start, end, duration, text",
    [
        (330, 300, 600.0, "must be before end"),
        (300, 300, 600.0, "must be before end"),
        (-1, 30, 600.0, "before the beginning"),
        (10, 61, 60.0, "after the end"),
    ],
)
def test_invalid_range_is_rejected_with_reason(start, end, duration, text):
    with pytest.raises(ExportError, match=text):
        resolve_range(start, end, duration)


def test_presets_give_expected_sizes():
    meta = make_clip(False).meta
    assert output_size(meta, "original") == (2160, 3840)
    assert output_size(meta, "social") == (1080, 1920)
    landscape = dataclasses.replace(meta, display_width=3840, display_height=2160)
    assert output_size(landscape, "social") == (1920, 1080)


def test_invalid_range_is_rejected_before_rendering(monkeypatch, tmp_path):
    monkeypatch.setattr(export_mod, "load_clip", lambda path, mount, **kwargs: make_clip(False))

    def must_not_render(*args, **kwargs):
        raise AssertionError("rendering started for an invalid range")

    monkeypatch.setattr(export_mod, "write_overlay_layer", must_not_render)
    with pytest.raises(ExportError, match="must be before end"):
        export("DJI_TEST_0051_D.MP4", {"timestamp": {}}, start=30, end=20,
               exports_dir=tmp_path, registry=_registry())
    assert list(tmp_path.iterdir()) == []


def test_overlay_needing_telemetry_is_rejected_for_clip_without_it(monkeypatch, tmp_path):
    monkeypatch.setattr(export_mod, "load_clip", lambda path, mount, **kwargs: make_clip(False))
    with pytest.raises(ExportError, match="'telemetry_stub' is unavailable.*no telemetry"):
        export("DJI_TEST_0051_D.MP4", {"telemetry_stub": {}}, exports_dir=tmp_path, registry=_registry())


def test_no_enabled_overlay_is_rejected(tmp_path):
    with pytest.raises(ExportError, match="no overlay is enabled"):
        export("DJI_TEST_0051_D.MP4", {"timestamp": {"enabled": False}}, exports_dir=tmp_path, registry=_registry())


def test_unreadable_source_names_the_file(tmp_path):
    with pytest.raises(ExportError, match="missing_clip.MP4"):
        export(tmp_path / "missing_clip.MP4", {"timestamp": {}}, exports_dir=tmp_path, registry=_registry())


def test_missing_ffmpeg_is_reported_as_export_error(monkeypatch, tmp_path):
    monkeypatch.setattr(ffmpeg_io.shutil, "which", lambda name: None)
    with pytest.raises(ExportError, match="ffmpeg"):
        export("DJI_TEST_0051_D.MP4", {"timestamp": {}}, exports_dir=tmp_path, registry=_registry())


# Real clip tests: 3 s ranges unless marked slow.


@requires_clip
def test_pass1_writes_one_frame_per_source_frame(tmp_path):
    ctx = _ctx_real()
    items = plan_layer(validate_config({"timestamp": {}}, _registry()), ctx, (300.0, 303.0), 2160, 3840)
    mov = tmp_path / "layer.mov"
    write_overlay_layer(items, 300.0, FPS, round(3 * float(FPS)), mov)

    expected = 3 * 59.94
    assert abs(_frame_count(mov) - expected) <= 1
    assert _video_stream(mov)["codec_name"] == "qtrle"


@requires_clip
@pytest.mark.parametrize(
    "preset, size",
    [("original", (2160, 3840)), ("social", (1080, 1920))],
)
def test_export_output_has_expected_format(tmp_path, preset, size):
    out = export(CLIP, {"timestamp": {}}, preset=preset, start=300, end=303,
                 exports_dir=tmp_path, registry=_registry())

    video = _video_stream(out)
    assert (video["width"], video["height"]) == size
    assert video["codec_name"] in ("hevc", "h264")
    if video["codec_name"] == "hevc":
        assert video["codec_tag_string"] == "hvc1"
    assert video["pix_fmt"] == "yuv420p"
    assert video["avg_frame_rate"] == "60000/1001"
    assert _frame_count(out) in (179, 180)

    info = ffmpeg_io.probe(out)
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert audio["codec_name"] == "aac"

    data = out.read_bytes()
    assert data.index(b"moov") < data.index(b"mdat"), "moov atom should come first (faststart)"


@requires_clip
def test_preview_layer_and_export_layer_are_pixel_identical(tmp_path):
    ctx = _ctx_real()
    configs = validate_config({"timestamp": {}}, _registry())
    start = 9.0
    items = plan_layer(configs, ctx, (start, start + 3.0), 2160, 3840)
    mov = tmp_path / "layer.mov"
    write_overlay_layer(items, start, FPS, 3 * 60, mov)
    frames = _decode_rgba(mov, *_size_of(items))

    i = 60
    t = start + i / float(FPS)
    # The preview draws the same overlay layer at the clip's display resolution.
    preview_items = plan_layer(configs, ctx, (0.0, ctx.meta.duration_s), 2160, 3840)
    preview_layer = render_layer(preview_items, t)
    assert preview_layer.size == _size_of(items)
    assert frames[i].tobytes() == preview_layer.tobytes()


@requires_clip
def test_repeated_export_keeps_both_files(tmp_path):
    first = export(CLIP, {"timestamp": {}}, start=300, end=301, exports_dir=tmp_path, registry=_registry())
    second = export(CLIP, {"timestamp": {}}, start=300, end=301, exports_dir=tmp_path, registry=_registry())
    assert first.name == "DJI_20261026155823_0051_D__timestamp__300-301.mp4"
    assert second.name == "DJI_20261026155823_0051_D__timestamp__300-301_2.mp4"
    assert first.exists() and second.exists()


@requires_clip
def test_cancel_stops_processes_and_removes_partial_output(tmp_path):
    progress_seen: list[float] = []
    processes = []

    def progress(fraction: float) -> None:
        progress_seen.append(fraction)

    with pytest.raises(ExportCancelled):
        export(
            CLIP, {"timestamp": {}}, start=300, end=303, exports_dir=tmp_path, registry=_registry(),
            progress=progress,
            should_cancel=lambda: bool(progress_seen) and progress_seen[-1] > 0.2,
            on_process=processes.append,
        )
    assert processes and all(p.poll() is not None for p in processes)
    assert list(tmp_path.iterdir()) == []
    assert progress_seen == sorted(progress_seen)


@requires_clip
@pytest.mark.slow
def test_export_300_to_330_lasts_30_seconds(tmp_path):
    out = export(CLIP, {"timestamp": {}}, start=300, end=330, exports_dir=tmp_path, registry=_registry())
    assert abs(_frame_count(out) - 30 * 59.94) <= 1


def _ctx_real():
    from app.render.clip import load_clip

    return load_clip(CLIP)


def _size_of(items) -> tuple[int, int]:
    x0, y0, x1, y1 = union_box(items)
    return x1 - x0, y1 - y0


def test_export_has_no_guides_option_and_never_draws_them():
    import inspect

    assert "guides" not in inspect.signature(export).parameters
    assert "draw_safe_guides" not in inspect.getsource(export_mod)


@pytest.mark.parametrize("start, end", [(float("nan"), 30.0), (0.0, float("nan")), (float("inf"), 30.0)])
def test_non_finite_range_is_rejected(start, end):
    with pytest.raises(ExportError, match="finite"):
        resolve_range(start, end, 60.0)


def test_hevc_output_is_tagged_hvc1():
    cmd = export_mod._pass2_cmd(
        Path("clip.MP4"), 0.0, 3.0, Path("layer.mov"), (0, 0), (1080, 1920), "hevc_nvenc", True, Path("out.mp4"),
    )
    tag = cmd[cmd.index("-tag:v") + 1]
    assert tag == "hvc1"


def test_h264_output_gets_no_hevc_tag():
    cmd = export_mod._pass2_cmd(
        Path("clip.MP4"), 0.0, 3.0, Path("layer.mov"), (0, 0), (1080, 1920), "h264_nvenc", True, Path("out.mp4"),
    )
    assert "-tag:v" not in cmd


def test_draw_error_stops_ffmpeg_and_propagates(tmp_path):
    class BrokenDraw(TimestampOverlay):
        id = "broken"

        def draw(self, img, t, state):
            raise OSError("overlay could not read its data")

    reg = OverlayRegistry()
    reg.register(BrokenDraw())
    items = plan_layer(validate_config({"broken": {}}, reg), make_clip(False), (0.0, 1.0), 1080, 1920)
    processes: list[subprocess.Popen] = []
    run = export_mod._Run(None, lambda: False, processes.append)
    outcome: dict[str, BaseException] = {}

    def write() -> None:
        try:
            write_overlay_layer(items, 0.0, FPS, 60, tmp_path / "layer.mov", run)
        except BaseException as exc:
            outcome["exc"] = exc

    # Before the fix this hung in proc.wait(), so the call runs in a thread with a deadline.
    worker = threading.Thread(target=write, daemon=True)
    worker.start()
    worker.join(timeout=60)
    assert not worker.is_alive(), "write_overlay_layer hung after a drawing error"
    assert isinstance(outcome.get("exc"), OSError)
    assert processes and all(p.poll() is not None for p in processes)


def test_draw_error_removes_placeholder_and_reraises(monkeypatch, tmp_path):
    class FailingDraw(TimestampOverlay):
        id = "failing"

        def draw(self, img, t, state):
            raise ValueError("bad overlay state")

    monkeypatch.setattr(export_mod, "load_clip", lambda path, mount, **kwargs: make_clip(False))
    reg = OverlayRegistry()
    reg.register(FailingDraw())
    with pytest.raises(ValueError, match="bad overlay state"):
        export("DJI_TEST_0051_D.MP4", {"failing": {}}, start=0, end=1, encoder="libx264",
               exports_dir=tmp_path, registry=reg)
    assert list(tmp_path.iterdir()) == []


def test_cancel_after_failed_pass2_attempt_starts_no_more_processes(monkeypatch, tmp_path):
    attempts: list[list[str]] = []

    def failing_attempt(run, cmd, duration):
        attempts.append(cmd)
        return False, False, "no usable device"

    monkeypatch.setattr(export_mod, "_run_pass2", failing_attempt)
    run = export_mod._Run(None, lambda: bool(attempts), None)
    with pytest.raises(ExportCancelled):
        export_mod._composite(
            run, Path("clip.MP4"), (0.0, 1.0), tmp_path / "layer.mov", (0, 0), (1080, 1920),
            "h264_nvenc", tmp_path / "out.mp4",
        )
    assert len(attempts) == 1
