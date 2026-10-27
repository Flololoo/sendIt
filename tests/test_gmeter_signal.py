import numpy as np
import pytest

from app.overlays.gmeter_signal import (
    BUMP_THRESHOLDS_G,
    bump_candidates,
    bump_events,
    bump_residual,
    decompose,
    decompose_samples,
    meter_components,
    travel_direction,
)
from app.overlays.lean_signal import gravity_in_camera, hann_smooth, lean_series, rotation_matrices

FS = 59.94


def axis_quat(axis: str, deg: float) -> np.ndarray:
    h = np.radians(deg) / 2
    w, s = np.cos(h), np.sin(h)
    return {"x": np.array([w, s, 0, 0]), "z": np.array([w, 0, 0, s])}[axis]


def quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ])


def pose(t: np.ndarray, yaw_deg, roll_deg=0.0) -> np.ndarray:
    """Quaternions for a camera with its x axis along the heading `yaw` and rolled by `roll` about x.

    Arrays of yaw values are accepted, one per sample. The roll is a constant.
    """
    yaw = np.broadcast_to(np.asarray(yaw_deg, dtype=float), t.shape)
    out = np.empty((len(t), 4))
    qr = axis_quat("x", roll_deg)
    for i, y in enumerate(yaw):
        out[i] = quat_mul(axis_quat("z", y), qr)
    return out


def telemetry_accel(quat: np.ndarray, a_world: np.ndarray) -> np.ndarray:
    """What the accelerometer reads: gravity at rest plus the linear acceleration, in camera axes."""
    r = rotation_matrices(quat)
    return gravity_in_camera(quat) + np.einsum("nji,nj->ni", r, a_world)


def heading_unit(yaw_deg: float) -> np.ndarray:
    a = np.radians(yaw_deg)
    return np.array([np.cos(a), np.sin(a), 0.0])


def right_unit(yaw_deg: float) -> np.ndarray:
    """Right of the heading in the z-down world frame, (-f_y, f_x)."""
    f = heading_unit(yaw_deg)
    return np.array([-f[1], f[0], 0.0])


def steady_ride(seconds: float, yaw_deg, roll_deg, a_world_fn):
    t = np.arange(int(seconds * FS)) / FS
    quat = pose(t, yaw_deg, roll_deg)
    a_world = np.array([a_world_fn(x) for x in t])
    return t, quat, telemetry_accel(quat, a_world)


def middle(x: np.ndarray, margin_s: float, t: np.ndarray) -> np.ndarray:
    return (t > t[0] + margin_s) & (t < t[-1] - margin_s)


# 1.1 gravity removal and the world frame


def test_at_rest_fixture_components_are_within_005_g(fixture_tel):
    s = fixture_tel.samples
    d = decompose_samples(s, "bike")
    lon, lat = meter_components(d)
    rest = s.t < 2.0  # the clip starts with the bike standing still
    vertical = hann_smooth(d.vertical, d.t, 0.4)
    assert np.abs(lon[rest]).max() < 0.05
    assert np.abs(lat[rest]).max() < 0.05
    assert np.abs(vertical[rest]).max() < 0.05


def test_no_linear_acceleration_gives_zero_components_at_any_lean():
    t, quat, accel = steady_ride(3.0, yaw_deg=0.0, roll_deg=30.0, a_world_fn=lambda _: np.zeros(3))
    d = decompose(t, quat, accel, "bike")
    assert np.abs(d.longitudinal).max() < 1e-9
    assert np.abs(d.lateral).max() < 1e-9
    assert np.abs(d.vertical).max() < 1e-9


def test_gravity_is_removed_while_leaning_and_turning():
    # Constant 0.3 g up in the world, camera leaned 35 degrees and heading 70 degrees.
    t, quat, accel = steady_ride(2.0, yaw_deg=70.0, roll_deg=35.0,
                                 a_world_fn=lambda _: np.array([0.0, 0.0, 0.3]))
    d = decompose(t, quat, accel, "bike")
    assert np.allclose(d.vertical, 0.3, atol=1e-9)
    assert np.abs(d.longitudinal).max() < 1e-9
    assert np.abs(d.lateral).max() < 1e-9


# 1.2 travel direction


@pytest.mark.parametrize("yaw", [0.0, 90.0, 179.0, -179.0, 300.0])
def test_steady_heading_is_recovered_on_both_mounts(yaw):
    t = np.arange(int(4 * FS)) / FS
    quat = pose(t, yaw)
    expected = heading_unit(yaw)[:2]
    for mount in ("bike", "helmet"):
        f = travel_direction(quat, t, mount)
        assert np.allclose(f, expected, atol=1e-6), mount


def test_helmet_glance_of_60_degrees_keeps_the_heading_within_5_degrees():
    t = np.arange(int(20 * FS)) / FS
    yaw = np.where((t >= 10.0) & (t < 10.5), 60.0, 0.0)
    quat = pose(t, yaw)
    f = travel_direction(quat, t, "helmet")
    heading = np.degrees(np.arctan2(f[:, 1], f[:, 0]))
    assert np.abs(heading).max() < 5.0


def test_bike_follows_a_glance_more_closely_than_helmet_does():
    t = np.arange(int(20 * FS)) / FS
    yaw = np.where((t >= 10.0) & (t < 10.5), 60.0, 0.0)
    quat = pose(t, yaw)
    bike = travel_direction(quat, t, "bike")
    helmet = travel_direction(quat, t, "helmet")
    assert np.degrees(np.arctan2(bike[:, 1], bike[:, 0])).max() > np.degrees(
        np.arctan2(helmet[:, 1], helmet[:, 0])
    ).max()


def test_braking_dot_stays_put_during_a_helmet_glance():
    # Riding straight at constant speed, braking at 0.4 g, with a 60 degree glance in between.
    yaw = lambda x: 60.0 if 10.0 <= x < 10.5 else 0.0  # noqa: E731
    t = np.arange(int(20 * FS)) / FS
    quat = pose(t, np.array([yaw(x) for x in t]))
    a_world = np.tile(np.array([-0.4, 0.0, 0.0]), (len(t), 1))  # along the bike's heading, yaw 0
    accel = telemetry_accel(quat, a_world)
    lon, lat = meter_components(decompose(t, quat, accel, "helmet"))
    window = (t > 10.6) & (t < 11.5)
    assert np.abs(lon[window] + 0.4).max() < 0.1
    assert np.abs(lat[window]).max() < 0.1


# 1.3 longitudinal and lateral signs


def test_known_deceleration_along_travel_is_negative_longitudinal():
    yaw, roll = 30.0, 25.0
    t, quat, accel = steady_ride(4.0, yaw, roll, lambda x: -0.4 * heading_unit(yaw))
    d = decompose(t, quat, accel, "bike")
    m = middle(t, 0.5, t)
    assert np.allclose(d.longitudinal[m], -0.4, atol=1e-6)
    assert np.abs(d.lateral[m]).max() < 1e-6
    assert np.abs(d.vertical[m]).max() < 1e-6


def test_known_acceleration_along_travel_is_positive_longitudinal():
    t, quat, accel = steady_ride(4.0, 0.0, 0.0, lambda x: 0.25 * heading_unit(0.0))
    lon, lat = meter_components(decompose(t, quat, accel, "bike"))
    assert lon[middle(t, 0.5, t)].mean() == pytest.approx(0.25, abs=1e-6)


@pytest.mark.parametrize("yaw", [0.0, 90.0, 210.0])
def test_known_right_turn_acceleration_is_positive_lateral(yaw):
    t, quat, accel = steady_ride(4.0, yaw, 20.0, lambda x: 0.4 * right_unit(yaw))
    d = decompose(t, quat, accel, "bike")
    m = middle(t, 0.5, t)
    assert np.allclose(d.lateral[m], 0.4, atol=1e-6)
    assert np.abs(d.longitudinal[m]).max() < 1e-6


def test_left_turn_acceleration_is_negative_lateral():
    t, quat, accel = steady_ride(4.0, 0.0, 0.0, lambda x: -0.4 * right_unit(0.0))
    d = decompose(t, quat, accel, "bike")
    assert d.lateral[middle(t, 0.5, t)].mean() == pytest.approx(-0.4, abs=1e-6)


# The lateral sign was checked against the lean overlay on the whole of clip 0051
# (corr +0.98 with tan(lean) in steady curves); the 5 s fixture is too short to pin it.


# 2.1 bump detection


def pulses(t: np.ndarray, events: list[tuple[float, float]], width_s: float = 0.02) -> np.ndarray:
    v = np.zeros_like(t)
    for at, peak in events:
        v += peak * np.exp(-0.5 * ((t - at) / width_s) ** 2)
    return v


def test_double_hit_0_3_s_apart_gives_one_event_with_the_larger_peak():
    t = np.arange(int(12 * FS)) / FS
    v = pulses(t, [(5.0, 1.5), (5.3, 2.0)])
    events = bump_candidates(t, v)
    assert len(events) == 1
    assert events[0].t == pytest.approx(5.3, abs=0.03)
    residual = bump_residual(v, t)
    assert events[0].peak_g == pytest.approx(residual[(t > 5.25) & (t < 5.35)].max(), abs=1e-9)
    assert events[0].peak_g > 1.7  # 2.0 g hit, minus the 1 s trend and sampling


def test_smooth_road_gives_no_events():
    t = np.arange(int(20 * FS)) / FS
    v = 0.2 * np.sin(2 * np.pi * 8.0 * t) + 0.05 * np.sin(2 * np.pi * 0.2 * t)
    for sensitivity in BUMP_THRESHOLDS_G:
        assert bump_events(t, v, sensitivity) == []


def test_engine_vibration_below_the_high_threshold_gives_no_events():
    t = np.arange(int(20 * FS)) / FS
    rng = np.random.default_rng(3)
    v = 0.15 * np.sin(2 * np.pi * 12.0 * t) + rng.normal(0, 0.05, len(t))
    assert bump_events(t, v, "high") == []


def test_sensitivity_levels_are_nested_on_synthetic_hits():
    t = np.arange(int(60 * FS)) / FS
    # Peaks sit well away from the thresholds, so the 1 s trend and sampling do not move them across.
    peaks = [0.65, 1.0, 1.6, 0.3, 2.2, 0.9, 1.5, 0.4]
    events = [(3.0 + 6.0 * i, p) for i, p in enumerate(peaks)]
    v = pulses(t, events)
    low = bump_events(t, v, "low")
    med = bump_events(t, v, "medium")
    high = bump_events(t, v, "high")
    assert [round(e.t) for e in low] == [15, 27, 39]
    assert [round(e.t) for e in med] == [9, 15, 27, 33, 39]
    assert [round(e.t) for e in high] == [3, 9, 15, 27, 33, 39]
    for lo, mid in ((low, med), (med, high)):
        for e in lo:
            assert any(abs(e.t - m.t) < 0.1 for m in mid)


def test_sensitivity_subset_property_on_random_events():
    rng = np.random.default_rng(11)
    t = np.arange(int(120 * FS)) / FS
    at = np.sort(rng.uniform(2.0, 118.0, 40))
    # keep the hits well apart so the random draw does not merge them
    at = at[np.concatenate(([True], np.diff(at) > 1.5))]
    peaks = rng.uniform(0.3, 2.0, len(at))
    v = pulses(t, list(zip(at, peaks))) + rng.normal(0, 0.02, len(t))
    low, med, high = (bump_events(t, v, s) for s in ("low", "medium", "high"))
    assert len(low) <= len(med) <= len(high)
    for lo, mid in ((low, med), (med, high)):
        for e in lo:
            assert any(abs(e.t - m.t) < 0.1 for m in mid)
    for e in low:
        assert e.peak_g >= BUMP_THRESHOLDS_G["low"]
    for e in high:
        assert e.peak_g >= BUMP_THRESHOLDS_G["high"]


def test_events_are_at_least_one_second_apart_and_sorted():
    rng = np.random.default_rng(5)
    t = np.arange(int(60 * FS)) / FS
    v = pulses(t, [(float(x), 1.0) for x in rng.uniform(2, 58, 30)]) + rng.normal(0, 0.03, len(t))
    events = bump_events(t, v, "high")
    times = [e.t for e in events]
    assert times == sorted(times)
    assert all(b - a >= 1.0 for a, b in zip(times, times[1:]))


def test_sensitivity_subset_property_on_fixture(fixture_tel):
    d = decompose_samples(fixture_tel.samples, "bike")
    low, med, high = (bump_events(d.t, d.vertical, s) for s in ("low", "medium", "high"))
    assert len(low) <= len(med) <= len(high)
    for lo, mid in ((low, med), (med, high)):
        for e in lo:
            assert any(abs(e.t - m.t) < 0.1 for m in mid)


def test_unknown_sensitivity_is_rejected():
    with pytest.raises(ValueError):
        bump_events(np.arange(10) / FS, np.zeros(10), "extreme")
