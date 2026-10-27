"""Lean overlay: registration, text, running maximum and golden images.

To regenerate the golden images after an intended change to the drawing, run
    python tests/test_lean_overlay.py --regen
and review the changed PNGs in tests/golden/ before committing them.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageChops, ImageFont

from app.overlays import ConfigError, default_registry, validate_config
from app.overlays.layer import LayerItem, render_layer
from app.overlays.lean import FONT_PATH, LEAN, LeanState, labels, max_texts, value_text

sys.path.insert(0, str(Path(__file__).parent))
from overlay_fixtures import make_clip  # noqa: E402

GOLDEN = Path(__file__).parent / "golden"
GOLDEN_VALUES = {"left": -17.6, "zero": 0.0, "right": 24.0}


def state_for(lean: float, show_max: bool = True, left: float = 18.0, right: float = 21.0) -> LeanState:
    t = np.array([0.0, 10.0])
    return LeanState(t, np.full(2, lean), np.full(2, left), np.full(2, right), show_max)


def render(lean: float) -> Image.Image:
    item = LayerItem(LEAN, (0, 0, *LEAN.base_box), state_for(lean))
    return render_layer([item], 1.0)


def test_font_loads_in_pillow():
    assert ImageFont.truetype(str(FONT_PATH), 40).getbbox("L 18°")[2] > 0
    assert (FONT_PATH.parent / "OFL.txt").exists()


def test_registered_with_settings(fixture_tel):
    assert default_registry.get("lean") is LEAN
    assert LEAN.requires_telemetry
    clip = make_clip(True)
    available = {o.id: a.available for o, a in default_registry.overlays_for(clip)}
    assert available["lean"]
    assert {s.key: s.default for s in LEAN.settings} == {"offset": 0.0, "show_max": True}
    off = next(s for s in LEAN.settings if s.key == "offset")
    assert (off.min, off.max) == (-15.0, 15.0)


def test_offset_must_be_a_half_degree_step():
    validate_config({"lean": {"settings": {"offset": 2.5}}})
    with pytest.raises(ConfigError):
        validate_config({"lean": {"settings": {"offset": 2.3}}})
    with pytest.raises(ConfigError):
        validate_config({"lean": {"settings": {"offset": 16.0}}})


@pytest.mark.parametrize(
    ("angle", "text"),
    [(-17.6, "L 18°"), (22.5, "R 23°"), (0.4, "0°"), (-0.4, "0°"), (65.0, "R 65°")],
)
def test_value_text(angle, text):
    assert value_text(angle) == text


def test_draw_shows_left_18_for_minus_17_6():
    assert labels(state_for(-17.6), 1.0)[0] == "L 18°"


def test_show_max_off_draws_no_maximum_text():
    assert labels(state_for(-17.6, show_max=False), 1.0) == ["L 18°"]
    with_max = labels(state_for(-17.6), 1.0)
    assert with_max[1:] == list(max_texts(18.0, 21.0))
    assert "max R 21°" in with_max
    plain = render(-17.6)
    off = render_layer([LayerItem(LEAN, (0, 0, *LEAN.base_box), state_for(-17.6, show_max=False))], 1.0)
    assert ImageChops.difference(plain, off).getbbox() is not None


def test_prepare_builds_the_running_maximum_from_the_range_start(fixture_tel):
    clip = make_clip(True)
    clip = type(clip)(path=clip.path, meta=fixture_tel.meta, telemetry=fixture_tel, mount="bike")
    state = LEAN.prepare(clip, {"offset": 0.0, "show_max": True}, (2.0, 5.0))
    before = state.t < 2.0
    assert not state.max_left[before].any() and not state.max_right[before].any()
    assert (np.diff(state.max_right) >= 0).all() and (np.diff(state.max_left) >= 0).all()


@pytest.mark.parametrize("name", sorted(GOLDEN_VALUES))
def test_golden_image(name):
    expected = Image.open(GOLDEN / f"lean_{name}.png").convert("RGBA")
    actual = render(GOLDEN_VALUES[name])
    assert actual.size == expected.size
    assert ImageChops.difference(actual, expected).getbbox() is None, (
        "overlay drawing changed; regenerate with: python tests/test_lean_overlay.py --regen"
    )


if __name__ == "__main__":
    if "--regen" not in sys.argv:
        sys.exit("pass --regen to overwrite the golden images")
    GOLDEN.mkdir(exist_ok=True)
    for key, value in GOLDEN_VALUES.items():
        render(value).save(GOLDEN / f"lean_{key}.png")
        print("wrote", GOLDEN / f"lean_{key}.png")
