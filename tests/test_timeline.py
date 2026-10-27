import numpy as np
import pytest

from app.telemetry.model import slerp


def test_first_timestamp_is_zero_and_monotonic(fixture_tel):
    t = fixture_tel.samples.t
    assert t[0] == 0.0
    assert np.all(np.diff(t) > 0)


def test_spacing_matches_frame_rate(fixture_tel):
    t = fixture_tel.samples.t
    mean_step = (t[-1] - t[0]) / (len(t) - 1)
    assert mean_step == pytest.approx(1 / 59.94, rel=1e-4)


def test_midpoint_orientation_is_between_neighbours_and_accel_is_mean(fixture_tel):
    s = fixture_tel.samples
    i = 40
    mid = (s.t[i] + s.t[i + 1]) / 2
    sample = fixture_tel.at(mid)

    q0, q1 = s.quat[i], s.quat[i + 1]
    assert np.linalg.norm(sample.quat) == pytest.approx(1.0)
    # Halfway along the arc: equal angle to both neighbours, summing to the full angle.
    angle_full = np.arccos(min(abs(np.dot(q0, q1)), 1.0))
    angle_to_0 = np.arccos(min(abs(np.dot(sample.quat, q0)), 1.0))
    angle_to_1 = np.arccos(min(abs(np.dot(sample.quat, q1)), 1.0))
    assert angle_to_0 == pytest.approx(angle_full / 2, abs=1e-6)
    assert angle_to_1 == pytest.approx(angle_full / 2, abs=1e-6)

    np.testing.assert_allclose(sample.accel, (s.accel[i] + s.accel[i + 1]) / 2, rtol=1e-9)


def test_exact_sample_time_returns_that_sample(fixture_tel):
    s = fixture_tel.samples
    sample = fixture_tel.at(s.t[7])
    np.testing.assert_array_equal(sample.quat, s.quat[7])
    np.testing.assert_array_equal(sample.accel, s.accel[7])
    assert sample.iso == s.iso[7]


def test_before_start_clamps_to_first_sample(fixture_tel):
    s = fixture_tel.samples
    sample = fixture_tel.at(-5.0)
    np.testing.assert_array_equal(sample.quat, s.quat[0])
    np.testing.assert_array_equal(sample.accel, s.accel[0])


def test_after_end_returns_last_record(fixture_tel):
    s = fixture_tel.samples
    sample = fixture_tel.at(s.t[-1] + 1000.0)
    np.testing.assert_array_equal(sample.quat, s.quat[-1])
    np.testing.assert_array_equal(sample.accel, s.accel[-1])


def test_exposure_is_taken_from_previous_record(fixture_tel):
    s = fixture_tel.samples
    mid = (s.t[3] + s.t[4]) / 2
    assert fixture_tel.at(mid).iso == s.iso[3]


def test_at_on_empty_telemetry_raises():
    from app.telemetry.model import Metadata, Samples, Telemetry

    meta = Metadata(
        source="x", telemetry_available=False, proto_schema=None, model=None, serial=None,
        firmware=None, width=1, height=1, fps=None, rotation=0, display_width=1,
        display_height=1, orientation="landscape", duration_s=0.0, start_utc=None, has_gps=False,
    )
    with pytest.raises(ValueError):
        Telemetry(samples=Samples.empty(), meta=meta).at(0.0)


def test_slerp_handles_opposite_sign_quaternions():
    q0 = np.array([1.0, 0.0, 0.0, 0.0])
    q1 = -q0  # same rotation, opposite sign: should stay put
    np.testing.assert_allclose(slerp(q0, q1, 0.5), q0, atol=1e-12)
