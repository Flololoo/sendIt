from pathlib import Path

from overlay_fixtures import TimestampOverlay, make_clip

from app.overlays.config import validate_config
from app.overlays.layer import LayerItem, plan_layer, render_layer, union_box
from app.overlays.registry import OverlayRegistry
from app.render.naming import export_stem


def _items():
    ts = TimestampOverlay()
    other = TimestampOverlay()
    other.id = "other"
    return [
        LayerItem(ts, (43, 230, 500, 350), {"decimals": 2, "unit": "s"}),
        LayerItem(other, (43, 400, 300, 520), {"decimals": 1, "unit": "ms"}),
    ]


def test_same_t_renders_byte_identical_images():
    items = _items()
    a = render_layer(items, 10.0)
    b = render_layer(items, 10.0)
    assert a.size == b.size
    assert a.tobytes() == b.tobytes()


def test_different_t_changes_the_image():
    items = _items()
    assert render_layer(items, 10.0).tobytes() != render_layer(items, 12.0).tobytes()


def test_layer_is_cropped_to_union_box():
    items = _items()
    assert union_box(items) == (43, 230, 500, 520)
    layer = render_layer(items, 1.0)
    assert layer.mode == "RGBA"
    assert layer.size == (500 - 43, 520 - 230)


def test_no_items_gives_empty_layer():
    assert render_layer([], 0.0).size == (0, 0)


def test_plan_layer_skips_disabled_and_prepares_enabled():
    reg = OverlayRegistry()
    reg.register(TimestampOverlay())
    configs = validate_config({"timestamp": {"settings": {"decimals": 1}}}, reg)
    items = plan_layer(configs, make_clip(with_telemetry=False), (0.0, 30.0), 1080, 1920)
    assert len(items) == 1
    assert items[0].state == {"decimals": 1, "unit": "s"}
    x0, y0, x1, y1 = items[0].box
    assert x0 >= 0.04 * 1080 and y0 >= 0.12 * 1920

    disabled = validate_config({"timestamp": {"enabled": False}}, reg)
    assert plan_layer(disabled, make_clip(with_telemetry=False), (0.0, 30.0), 1080, 1920) == []


def test_config_key_order_does_not_change_layout_or_names():
    reg = OverlayRegistry()
    reg.register(TimestampOverlay())
    other = TimestampOverlay()
    other.id = "other"
    reg.register(other)
    clip = make_clip(with_telemetry=False)

    forward = validate_config({"timestamp": {}, "other": {}}, reg)
    backward = validate_config({"other": {}, "timestamp": {}}, reg)
    # Both default to top-left, so the stacking order shows in the boxes.
    a = plan_layer(forward, clip, (0.0, 30.0), 1080, 1920)
    b = plan_layer(backward, clip, (0.0, 30.0), 1080, 1920)

    assert [(i.overlay.id, i.box) for i in a] == [(i.overlay.id, i.box) for i in b]
    assert [i.overlay.id for i in a] == ["timestamp", "other"]
    name_a = export_stem(Path("clip.MP4"), [c.overlay.id for c in forward.values()], 0.0, 30.0)
    name_b = export_stem(Path("clip.MP4"), [c.overlay.id for c in backward.values()], 0.0, 30.0)
    assert name_a == name_b == "clip__timestamp+other__0-30"
