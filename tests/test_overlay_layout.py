import itertools

import pytest

from app.overlays.contract import POSITIONS
from app.overlays.layout import Placement, place_overlays, preset_box, safe_area

BASE = (400, 300)
FRAMES = [(1080, 1920), (2160, 3840)]


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("size", ["S", "M", "L"])
@pytest.mark.parametrize("w,h", FRAMES)
def test_preset_box_inside_safe_area(position, size, w, h):
    box = preset_box(position, size, BASE, w, h)
    assert safe_area(w, h).contains(box)


@pytest.mark.parametrize("position", POSITIONS)
def test_preset_box_has_identical_relative_geometry(position):
    (w1, h1), (w2, h2) = FRAMES
    a = preset_box(position, "M", BASE, w1, h1)
    b = preset_box(position, "M", BASE, w2, h2)
    for attr, ref1, ref2 in [("x0", w1, w2), ("x1", w1, w2), ("y0", h1, h2), ("y1", h1, h2)]:
        assert getattr(a, attr) / ref1 == pytest.approx(getattr(b, attr) / ref2)


def test_size_scaling_ratios():
    s = preset_box("middle-left", "S", BASE, 1080, 1920)
    m = preset_box("middle-left", "M", BASE, 1080, 1920)
    l = preset_box("middle-left", "L", BASE, 1080, 1920)
    assert s.width == pytest.approx(BASE[0] * 0.75)
    assert m.width == pytest.approx(BASE[0] * 1.0)
    assert l.width == pytest.approx(BASE[0] * 1.35)


def test_bottom_right_lies_above_bottom_and_left_of_right_inset():
    box = preset_box("bottom-right", "M", BASE, 1080, 1920)
    assert box.y1 <= 1920 * (1 - 0.25) + 1e-6
    assert box.x1 <= 1080 * (1 - 0.15) + 1e-6


@pytest.mark.parametrize("position", POSITIONS)
def test_two_overlays_sharing_a_position_do_not_intersect(position):
    placements = [
        Placement("a", position, "M", BASE),
        Placement("b", position, "M", BASE),
    ]
    boxes = place_overlays(placements, 1080, 1920)
    assert not boxes["a"].intersects(boxes["b"])
    assert safe_area(1080, 1920).contains(boxes["a"])
    assert safe_area(1080, 1920).contains(boxes["b"])


def test_stack_keeps_registry_order_from_edge():
    placements = [
        Placement("first", "top-left", "M", BASE),
        Placement("second", "top-left", "M", BASE),
    ]
    boxes = place_overlays(placements, 1080, 1920)
    assert boxes["first"].y0 < boxes["second"].y0
    assert boxes["first"].y0 == pytest.approx(safe_area(1080, 1920).y0)


def test_bottom_stack_first_overlay_sits_on_bottom_edge():
    placements = [
        Placement("first", "bottom-right", "M", BASE),
        Placement("second", "bottom-right", "M", BASE),
    ]
    boxes = place_overlays(placements, 1080, 1920)
    assert boxes["first"].y1 == pytest.approx(safe_area(1080, 1920).y1)
    assert boxes["second"].y1 < boxes["first"].y0


def test_stack_that_does_not_fit_is_rejected():
    big = [Placement(str(i), "top-left", "L", (400, 800)) for i in range(2)]
    with pytest.raises(ValueError, match="does not fit"):
        place_overlays(big, 1080, 1920)


def test_unknown_position_is_rejected():
    with pytest.raises(ValueError, match="unknown position"):
        place_overlays([Placement("a", "centre", "M", BASE)], 1080, 1920)
