"""Sign check of the lean angle against footage of clip 0051. Skipped when videos/ is absent."""

from pathlib import Path

import numpy as np
import pytest

from app.overlays.lean_signal import lean_series
from app.telemetry import get_telemetry

CLIP = Path(__file__).resolve().parents[1] / "videos" / "DJI_20261026155823_0051_D.MP4"

# Picked by watching the footage: the camera tilts into a right-hand curve at 116.9 s,
# into a left-hand curve at 422.4 s, and the road is straight from 46 s to 57 s.
RIGHT_CURVE_S = 116.9
LEFT_CURVE_S = 422.4
STRAIGHT_S = (46.0, 57.0)


@pytest.fixture(scope="module")
def series():
    if not CLIP.exists():
        pytest.skip(f"{CLIP} not present")
    return lean_series(get_telemetry(CLIP), "bike")


def test_right_curve_is_positive(series):
    t, lean = series
    assert lean[np.searchsorted(t, RIGHT_CURVE_S)] > 10


def test_left_curve_is_negative(series):
    t, lean = series
    assert lean[np.searchsorted(t, LEFT_CURVE_S)] < -10


def test_straight_segment_is_near_zero(series):
    t, lean = series
    window = (t >= STRAIGHT_S[0]) & (t <= STRAIGHT_S[1])
    assert np.abs(lean[window]).max() < 3.0
