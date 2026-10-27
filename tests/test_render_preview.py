import importlib
from pathlib import Path

import numpy as np
import pytest
from overlay_fixtures import RangeRecordingOverlay, TimestampOverlay, make_clip
from PIL import Image, ImageChops

from app.overlays.registry import OverlayRegistry
from app.render.clip import preview_source
from app.render.preview import GUIDE_COLOR, grab_frame, preview

preview_mod = importlib.import_module("app.render.preview")

CLIP = Path(__file__).resolve().parents[1] / "videos" / "DJI_20261026155823_0051_D.MP4"
requires_clip = pytest.mark.skipif(not CLIP.exists(), reason="needs clip 0051 in videos/")


def _registry() -> OverlayRegistry:
    reg = OverlayRegistry()
    reg.register(TimestampOverlay())
    return reg


def test_preview_source_prefers_lrf_next_to_mp4(tmp_path):
    mp4 = tmp_path / "clip_0001.MP4"
    lrf = tmp_path / "clip_0001.LRF"
    mp4.write_bytes(b"")
    assert preview_source(mp4) == mp4
    lrf.write_bytes(b"")
    assert preview_source(mp4) == lrf


@requires_clip
def test_grab_frame_is_portrait_and_720_wide():
    img = grab_frame(preview_source(CLIP), 300.0)
    assert img.width == 720
    assert img.height > img.width
    assert img.height == 1280


@requires_clip
def test_guides_appear_only_when_requested():
    cfg = {"timestamp": {}}
    plain = preview(CLIP, 10.0, cfg, guides=False, registry=_registry())
    again = preview(CLIP, 10.0, cfg, guides=False, registry=_registry())
    guided = preview(CLIP, 10.0, cfg, guides=True, registry=_registry())

    assert plain.tobytes() == again.tobytes()
    diff = ImageChops.difference(plain, guided)
    assert diff.getbbox() is not None, "guides should change the image"

    # Only the guide outline changes: every pixel that differs is the guide colour.
    mask = np.any(np.asarray(plain) != np.asarray(guided), axis=2)
    assert mask.any()
    assert np.all(np.asarray(guided)[mask] == np.array(GUIDE_COLOR[:3], dtype=np.uint8))


@requires_clip
def test_preview_draws_the_overlay_layer():
    cfg = {"timestamp": {}}
    with_overlay = preview(CLIP, 10.0, cfg, registry=_registry())
    without = preview(CLIP, 10.0, {"timestamp": {"enabled": False}}, registry=_registry())
    assert ImageChops.difference(with_overlay, without).getbbox() is not None


def test_preview_prepares_overlays_for_the_export_range(monkeypatch):
    monkeypatch.setattr(preview_mod, "load_clip", lambda path, mount="bike", **kwargs: make_clip(False))
    monkeypatch.setattr(
        preview_mod, "grab_frame",
        lambda source, t, width=preview_mod.PREVIEW_WIDTH: Image.new("RGB", (width, 1280)),
    )
    reg = OverlayRegistry()
    overlay = RangeRecordingOverlay()
    reg.register(overlay)
    cfg = {"range_recording": {}}

    preview("DJI_TEST_0051_D.MP4", 304.0, cfg, registry=reg, start=10, end=40)
    preview("DJI_TEST_0051_D.MP4", 304.0, cfg, registry=reg)

    assert overlay.prepared == [(10.0, 40.0), (0.0, 60.0)]
