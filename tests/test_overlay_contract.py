from overlay_fixtures import make_clip

from app.overlays.contract import ClipContext


def test_default_mount_is_bike():
    clip = make_clip(with_telemetry=False)
    assert clip.mount == "bike"
    assert ClipContext(path=clip.path, meta=clip.meta, telemetry=None).mount == "bike"


def test_explicit_mount_is_kept():
    assert make_clip(with_telemetry=False, mount="helmet").mount == "helmet"
