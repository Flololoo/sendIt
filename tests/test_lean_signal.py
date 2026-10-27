import numpy as np
import pytest

from app.overlays.lean_signal import (
    CANDIDATES,
    CONVENTION,
    LEAN_LIMIT_DEG,
    Convention,
    circular_median_deg,
    gravity_in_camera,
    heading_rate_deg_s,
    lean_from_roll,
    lean_series,
    roll_deg,
    select_convention,
    upright_reference,
)

FS = 59.94


def roll_quat(phi_deg: float, yaw_deg: float = 0.0) -> np.ndarray:
    """Unit quaternion (w, x, y, z) of a camera that looks forward with its y axis pointing down, rolled by phi."""
    ax = np.radians(phi_deg + 90) / 2
    qx = np.array([np.cos(ax), np.sin(ax), 0.0, 0.0])
    az = np.radians(yaw_deg) / 2
    qz = np.array([np.cos(az), 0.0, 0.0, np.sin(az)])
    w1, x1, y1, z1 = qz
    w2, x2, y2, z2 = qx
    return np.array([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ])


def test_gravity_of_known_rotations():
    q = np.array([roll_quat(0.0), roll_quat(30.0)])
    g = gravity_in_camera(q)
    assert np.allclose(np.linalg.norm(g, axis=1), 1.0)
    assert np.allclose(g[0], [0, -1, 0], atol=1e-9)
    assert np.allclose(g[1], [0, -np.cos(np.radians(30)), np.sin(np.radians(30))], atol=1e-9)


def test_component_order_and_inverse_are_distinguishable():
    q = roll_quat(30.0)[None]
    reordered = q[:, [1, 2, 3, 0]]
    same = gravity_in_camera(reordered, Convention("xyzw", CONVENTION.inverse, CONVENTION.sign))
    assert np.allclose(same, gravity_in_camera(q))
    other = gravity_in_camera(q, Convention("wxyz", not CONVENTION.inverse, CONVENTION.sign))
    assert not np.allclose(other, gravity_in_camera(q))


def test_convention_check_picks_the_right_candidate_on_synthetic_data():
    t = np.arange(600) / FS
    quat = np.array([roll_quat(15 * np.sin(x)) for x in t])
    accel = gravity_in_camera(quat) * 1.0
    conv, err = select_convention(quat, accel, t)
    assert conv == CONVENTION
    assert err < 3.0
    assert len(CANDIDATES) == 8


def test_convention_check_on_committed_fixture(fixture_tel):
    s = fixture_tel.samples
    conv, err = select_convention(s.quat, s.accel, s.t)
    assert conv == CONVENTION
    assert err < 5.0


@pytest.mark.parametrize("phi", [-40.0, -12.5, 0.0, 7.0, 33.0])
def test_roll_about_the_viewing_axis_returns_the_input_angle(phi):
    roll = roll_deg(gravity_in_camera(roll_quat(phi)[None]))
    assert roll[0] == pytest.approx(phi, abs=1e-9)


def test_heading_rate_of_a_steady_turn():
    t = np.arange(300) / FS
    quat = np.array([roll_quat(0.0, yaw_deg=10.0 * x) for x in t])
    rate = heading_rate_deg_s(quat, t)
    assert np.allclose(rate[5:-5], rate[100], atol=1e-6)
    assert abs(rate[100]) == pytest.approx(10.0, abs=1e-6)


def synthetic_ride(seconds_straight: float, mount_roll: float = 37.0):
    """A straight stretch, a curve with a 25-degree lean peak, then another straight stretch."""
    t = np.arange(int((seconds_straight * 2 + 6) * FS)) / FS
    lean = np.zeros_like(t)
    rate = np.zeros_like(t)
    curve = (t >= seconds_straight) & (t < seconds_straight + 6)
    lean[curve] = 25 * np.sin(np.pi * (t[curve] - seconds_straight) / 6)
    rate[curve] = 15.0
    return t, mount_roll + lean, rate, lean


def test_straight_segment_reads_zero_and_mount_angle_is_absorbed():
    t, roll, rate, lean = synthetic_ride(15.0)
    out = lean_from_roll(roll, rate, t, "bike")
    assert np.abs(out[t < 14]).max() < 0.5
    assert out.max() == pytest.approx(25.0, abs=1.5)


def test_reference_falls_back_to_median_when_straight_riding_is_short():
    t, roll, rate, _ = synthetic_ride(4.0)  # 8 s of straight riding in total
    ref = upright_reference(roll, rate, t)
    assert ref == pytest.approx(circular_median_deg(roll))
    out = lean_from_roll(roll, rate, t, "bike")
    assert np.isfinite(out).all()


def test_circular_median_handles_wraparound():
    assert circular_median_deg(np.array([179.0, -179.0, 178.0, -178.0, 180.0])) == pytest.approx(180.0, abs=1.5) or \
        abs(circular_median_deg(np.array([179.0, -179.0, 178.0, -178.0, 180.0]))) == pytest.approx(180.0, abs=1.5)


def test_clamp_and_additive_offset():
    t = np.arange(600) / FS
    roll = np.full_like(t, 80.0)
    roll[:500] = 0.0
    rate = np.zeros_like(t)
    out = lean_from_roll(roll, rate, t, "bike")
    assert out.max() == LEAN_LIMIT_DEG
    t, roll, rate, _ = synthetic_ride(15.0)
    base = lean_from_roll(roll, rate, t, "bike")
    shifted = lean_from_roll(roll, rate, t, "bike", offset=2.0)
    assert np.allclose(shifted, base + 2.0)


def test_helmet_is_smoother_than_bike_with_the_same_peaks():
    t, roll, rate, _ = synthetic_ride(15.0)
    rng = np.random.default_rng(1)
    roll = roll + rng.normal(0, 2.0, len(t))
    bike = lean_from_roll(roll, rate, t, "bike")
    helmet = lean_from_roll(roll, rate, t, "helmet")
    assert np.diff(helmet).var() < np.diff(bike).var()


def test_smoothing_does_not_shift_the_signal():
    t, roll, rate, lean = synthetic_ride(15.0)
    for mount in ("bike", "helmet"):
        out = lean_from_roll(roll, rate, t, mount)
        assert abs(t[np.argmax(out)] - t[np.argmax(lean)]) < 0.1


def test_lean_series_on_fixture(fixture_tel):
    t, lean = lean_series(fixture_tel, "bike")
    assert len(t) == len(fixture_tel)
    assert np.isfinite(lean).all()
    assert np.abs(lean).max() <= LEAN_LIMIT_DEG
