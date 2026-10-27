"""G-meter overlay: registration, validation, series and events, text, and golden images.

To regenerate the golden images after an intended change to the drawing, run
    python tests/test_gmeter_overlay.py --regen
and review the changed PNGs in tests/golden/ before committing them.
"""

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageChops

from app.overlays import ConfigError, default_registry, validate_config
from app.overlays.gmeter import (
    GMETER,
    GMeterState,
    TRAIL_POINTS,
    _to_screen,
    bump_count,
    callout_at,
    count_text,
    dot_position,
    labels,
    ring_radius,
    trail_times,
    value_text,
)
from app.overlays.layer import LayerItem, render_layer
from app.telemetry import Samples, Telemetry

sys.path.insert(0, str(Path(__file__).parent))
from overlay_fixtures import make_clip  # noqa: E402
from test_gmeter_signal import FS, pose, telemetry_accel  # noqa: E402

GOLDEN = Path(__file__).parent / "golden"
BOX = GMETER.base_box


def meter_state(long: float = 0.0, lat: float = 0.0, events=(), show_meter=True, show_bumps=True,
                show_count=True) -> GMeterState:
    t = np.linspace(0.0, 10.0, 601)
    ev_t = np.array([e[0] for e in events], dtype=float)
    ev_p = np.array([e[1] for e in events], dtype=float)
    count = np.searchsorted(ev_t, t, side="right").astype(int)
    return GMeterState(
        t, np.full_like(t, long), np.full_like(t, lat), ev_t, ev_p, count,
        show_meter, show_bumps, show_count,
    )


def render(state: GMeterState, t: float) -> Image.Image:
    return render_layer([LayerItem(GMETER, (0, 0, *BOX), state)], t)


def ride_clip(bump_times_s: list[float], duration_s: float = 60.0, mount: str = "bike"):
    """A straight, level ride at constant speed with 1.5 g vertical hits at the given times."""
    t = np.arange(int(duration_s * FS)) / FS
    quat = pose(t, 0.0)
    a_world = np.zeros((len(t), 3))
    for at in bump_times_s:
        a_world[:, 2] += 1.5 * np.exp(-0.5 * ((t - at) / 0.02) ** 2)
    accel = telemetry_accel(quat, a_world)
    base = make_clip(True, mount)
    samples = Samples(
        t=t, quat=quat, accel=accel,
        iso=np.full(len(t), 100.0), shutter_s=np.full(len(t), 1 / 500), wb_k=np.full(len(t), 5500.0),
    )
    tel = Telemetry(samples=samples, meta=base.meta)
    return replace(base, telemetry=tel, mount=mount)


CFG = {"show_meter": True, "show_bumps": True, "show_bump_count": True, "sensitivity": "medium"}


# registration and settings


def test_registered_with_the_four_settings():
    assert default_registry.get("gmeter") is GMETER
    assert GMETER.name == "G-meter & bumps"
    assert GMETER.requires_telemetry
    assert {s.key: s.default for s in GMETER.settings} == {
        "show_meter": True, "show_bumps": True, "show_bump_count": True, "sensitivity": "medium",
    }
    sens = next(s for s in GMETER.settings if s.key == "sensitivity")
    assert sens.type == "enum" and sens.choices == ("low", "medium", "high")
    assert GMETER.default_position == "middle-right"
    assert GMETER.default_size == "M"
    assert GMETER.base_box == (300, 360)


def test_listed_only_for_clips_with_telemetry():
    with_tel = {o.id: a.available for o, a in default_registry.overlays_for(make_clip(True))}
    without = {o.id: a.available for o, a in default_registry.overlays_for(make_clip(False))}
    assert with_tel["gmeter"] is True
    assert without["gmeter"] is False


def test_both_parts_off_is_rejected_through_validate_config():
    with pytest.raises(ConfigError) as err:
        validate_config({"gmeter": {"settings": {"show_meter": False, "show_bumps": False}}})
    assert any("at least one part must be shown" in e for e in err.value.errors)


@pytest.mark.parametrize("settings", [{"show_meter": False}, {"show_bumps": False}, {}])
def test_one_part_or_both_on_is_accepted(settings):
    resolved = validate_config({"gmeter": {"settings": settings}})
    assert "gmeter" in resolved


def test_sensitivity_must_be_one_of_the_three_levels():
    validate_config({"gmeter": {"settings": {"sensitivity": "high"}}})
    with pytest.raises(ConfigError):
        validate_config({"gmeter": {"settings": {"sensitivity": "extreme"}}})


# prepare: series, events and the count from the range start


def test_count_is_zero_at_the_range_start_and_counts_inside_the_range():
    clip = ride_clip([20.0, 25.0, 30.0, 45.0])
    state = GMETER.prepare(clip, CFG, (21.0, 40.0))
    assert bump_count(state, 21.0) == 0
    assert bump_count(state, 24.9) == 0
    assert bump_count(state, 25.5) == 1
    assert bump_count(state, 30.5) == 2
    assert bump_count(state, 40.0) == 2  # the hit at 45 s is outside the range
    assert labels(state, 21.0)[0] == value_text(0.0)
    assert labels(state, 21.0)[-1] == count_text(0)  # the call-out of the 20 s hit may still be showing


def test_events_are_found_with_their_peaks():
    clip = ride_clip([20.0, 25.0])
    state = GMETER.prepare(clip, CFG, (0.0, 60.0))
    assert len(state.event_t) == 2
    assert state.event_t == pytest.approx([20.0, 25.0], abs=0.03)
    assert (state.event_peak > 1.2).all()


def test_sensitivity_setting_is_passed_to_the_event_detector():
    clip = ride_clip([20.0])
    high = GMETER.prepare(clip, {**CFG, "sensitivity": "high"}, (0.0, 60.0))
    assert len(high.event_t) == 1


def test_prepare_without_telemetry_gives_an_empty_state():
    state = GMETER.prepare(make_clip(False), CFG, (0.0, 10.0))
    assert len(state.t) == 0
    assert labels(state, 5.0) == [value_text(0.0), count_text(0)]


# text and timing


def test_braking_text_is_0_4_g():
    state = meter_state(long=-0.4)
    assert labels(state, 5.0)[0] == "0.4 g"
    assert value_text(0.04) == "0.0 g"


def test_total_text_uses_the_horizontal_magnitude():
    state = meter_state(long=0.3, lat=0.4)
    assert labels(state, 5.0)[0] == "0.5 g"


def test_callout_is_fully_visible_for_1_s_then_fades_out_by_1_5_s():
    state = meter_state(events=[(324.2, 1.4)])
    assert "BUMP 1.4 g" in labels(state, 324.2)
    text, alpha = callout_at(state, 325.2)
    assert text == "BUMP 1.4 g" and alpha == pytest.approx(1.0)
    _, mid = callout_at(state, 325.45)
    assert mid == pytest.approx(0.5)
    assert callout_at(state, 325.75) is None


def test_newer_event_replaces_a_callout_still_showing():
    state = meter_state(events=[(10.0, 1.2), (10.3, 1.5)])
    assert callout_at(state, 10.5) == ("BUMP 1.5 g", pytest.approx(1.0))
    assert "BUMP 1.2 g" not in labels(state, 10.5)


def test_no_callout_before_the_first_event():
    state = meter_state(events=[(10.0, 1.2)])
    assert callout_at(state, 9.9) is None


def test_counter_is_hidden_when_show_bump_count_is_off():
    state = meter_state(events=[(3.0, 1.0)], show_count=False)
    assert all(not text.startswith("Bumps") for text in labels(state, 4.0))


def test_meter_text_is_hidden_when_the_meter_is_off():
    state = meter_state(long=-0.4, events=[(3.0, 1.0)], show_meter=False)
    assert labels(state, 3.5) == ["BUMP 1.0 g", "Bumps: 1"]


def test_bumps_are_hidden_when_show_bumps_is_off():
    state = meter_state(long=-0.4, events=[(3.0, 1.0)], show_bumps=False)
    assert labels(state, 3.5) == ["0.4 g"]


# geometry


def test_braking_dot_is_below_centre_at_0_4_of_the_1_g_ring():
    state = meter_state(long=-0.4)
    x, y = dot_position(state, 5.0)
    cx, cy = 150, 190
    assert x == pytest.approx(cx)
    assert (y - cy) == pytest.approx(0.4 * ring_radius(1.0))
    assert ring_radius(1.0) == pytest.approx(80.0)


def test_accelerating_dot_is_above_centre_and_lateral_right_is_to_the_right():
    x, y = dot_position(meter_state(long=0.5), 5.0)
    assert y < 190 and x == pytest.approx(150)
    x, y = dot_position(meter_state(lat=0.5), 5.0)
    assert x > 150 and y == pytest.approx(190)


def test_values_beyond_1_2_g_are_drawn_at_the_edge():
    x, y = _to_screen(2.0, 0.0, 80.0)
    assert x == pytest.approx(150 + 96.0)
    assert y == pytest.approx(190.0)
    x, y = _to_screen(0.0, -3.0, 80.0)
    assert y == pytest.approx(190 + 96.0)


def test_trail_covers_the_last_second_in_about_15_points():
    times = trail_times(10.0)
    assert len(times) == TRAIL_POINTS
    assert times[-1] == pytest.approx(10.0)
    assert times[0] == pytest.approx(9.0)


def test_draw_is_pure_for_a_given_time():
    state = meter_state(long=-0.4, events=[(3.0, 1.4)])
    assert ImageChops.difference(render(state, 3.5), render(state, 3.5)).getbbox() is None


# golden images


def golden_cases():
    braking = meter_state(long=-0.4)
    callout = meter_state(long=-0.4, events=[(5.0, 1.4)])
    fade = meter_state(long=-0.4, events=[(5.0, 1.4)])
    meter_off = meter_state(long=-0.4, events=[(5.0, 1.4)], show_meter=False)
    return {
        "braking": (braking, 5.0),
        "callout": (callout, 5.5),
        "fade": (fade, 6.25),
        "meter_off": (meter_off, 5.5),
    }


@pytest.mark.parametrize("name", sorted(golden_cases()))
def test_golden_image(name):
    state, t = golden_cases()[name]
    expected = Image.open(GOLDEN / f"gmeter_{name}.png").convert("RGBA")
    actual = render(state, t)
    assert actual.size == expected.size == BOX
    assert ImageChops.difference(actual, expected).getbbox() is None, (
        "overlay drawing changed; regenerate with: python tests/test_gmeter_overlay.py --regen"
    )


def test_meter_off_draws_only_in_the_top_region():
    state, t = golden_cases()["meter_off"]
    alpha = render(state, t).getchannel("A")
    # The resampling halo of the backing edge reaches a few pixels below the region.
    assert alpha.crop((0, 102, BOX[0], BOX[1])).getbbox() is None
    assert alpha.crop((0, 0, BOX[0], 96)).getbbox() is not None


def test_meter_off_with_nothing_to_show_draws_nothing():
    state = meter_state(long=-0.4, show_meter=False, show_count=False)
    assert render(state, 5.0).getchannel("A").getbbox() is None


if __name__ == "__main__":
    if "--regen" not in sys.argv:
        sys.exit("pass --regen to overwrite the golden images")
    GOLDEN.mkdir(exist_ok=True)
    for key, (state, t) in golden_cases().items():
        path = GOLDEN / f"gmeter_{key}.png"
        render(state, t).save(path)
        print("wrote", path)
