import struct

import numpy as np
import pytest

from app.telemetry.decoder import decode_header, decode_record
from app.telemetry.protobuf import DecodeError
from helpers import fixture_telemetry, load_fixture_parts


def _ld(number: int, payload: bytes) -> bytes:
    """Length-delimited field (payload shorter than 128 bytes)."""
    assert len(payload) < 128
    return bytes([(number << 3) | 2, len(payload)]) + payload


def _f32(number: int, value: float) -> bytes:
    return bytes([(number << 3) | 5]) + struct.pack("<f", value)


def test_fixture_decodes_every_record(fixture_tel):
    assert len(fixture_tel) == 300
    assert fixture_tel.skipped == 0


def test_first_frame_values(fixture_tel):
    s = fixture_tel.samples
    assert abs(np.linalg.norm(s.accel[0]) - 1.0) <= 0.1
    assert s.iso[0] == pytest.approx(100.0)
    assert s.shutter_s[0] == pytest.approx(1 / 250)
    assert s.wb_k[0] == pytest.approx(9555.0)


def test_quaternion_norm_and_accel_magnitude_across_fixture(fixture_tel):
    s = fixture_tel.samples
    assert np.all(np.abs(np.linalg.norm(s.quat, axis=1) - 1.0) <= 0.01)
    assert np.median(np.linalg.norm(s.accel, axis=1)) == pytest.approx(1.0, abs=0.05)


def test_quaternion_is_read_as_w_x_y_z(fixture_tel):
    # First record of clip 0051: w=0.774, x=0.626, y=-0.075, z=0.064.
    q = fixture_tel.samples.quat[0]
    assert q[0] == pytest.approx(0.7738776803016663, rel=1e-6)
    assert q[1] == pytest.approx(0.6256582736968994, rel=1e-6)
    assert q[2] == pytest.approx(-0.07455410063266754, rel=1e-6)
    assert q[3] == pytest.approx(0.06408412009477615, rel=1e-6)


def test_absent_exposure_fields_are_nan_and_absent_components_are_zero():
    quat = _f32(1, 1.0)  # w=1, x=y=z absent (proto3 default 0.0)
    accel = _f32(2, 1.0)  # x=1, y and z absent
    block = _ld(9, quat) + _ld(10, accel)
    record = _ld(3, _ld(2, block))
    rec = decode_record(record)
    assert rec.quat == (1.0, 0.0, 0.0, 0.0)
    assert rec.accel == (1.0, 0.0, 0.0)
    assert np.isnan(rec.iso) and np.isnan(rec.shutter_s) and np.isnan(rec.wb_k)
    assert rec.gps is False


def test_gps_flag_set_only_for_non_empty_submessage():
    base = _ld(9, _f32(1, 1.0)) + _ld(10, _f32(2, 1.0))
    empty_gps = _ld(3, _ld(2, base + _ld(11, b"")))
    filled_gps = _ld(3, _ld(2, base + _ld(12, b"\x08\x01")))
    assert decode_record(empty_gps).gps is False
    assert decode_record(filled_gps).gps is True


def test_record_without_sensor_block_raises():
    with pytest.raises(DecodeError):
        decode_record(b"\x08\x01")


def test_record_without_accel_block_raises():
    record = _ld(3, _ld(2, _ld(9, _f32(1, 1.0))))
    with pytest.raises(DecodeError):
        decode_record(record)


def test_header_fields_from_first_packet():
    raw, _, sizes, _ = load_fixture_parts()
    assert decode_header(raw[: sizes[0]]) == {
        "proto_schema": "dvtm_ac203.proto",
        "serial": "6S6VNCG00A0LN8",
        "firmware": "10.00.42.03",
        "model": "DJI OsmoAction4",
    }


def test_truncated_record_is_skipped_and_counted():
    raw, _, sizes, _ = load_fixture_parts()
    k = 10
    offset = sum(sizes[:k])
    truncated = raw[offset : offset + 10]  # only the first 10 bytes of record k survive
    new_raw = raw[:offset] + truncated + raw[offset + sizes[k] :]
    new_sizes = list(sizes)
    new_sizes[k] = 10

    tel = fixture_telemetry(raw=new_raw, sizes=new_sizes)
    assert len(tel) == 299
    assert tel.skipped == 1
    assert len(tel.samples.t) == len(tel.samples.quat) == len(tel.samples.accel) == 299


def test_garbage_record_is_skipped_and_rest_decodes():
    raw, _, sizes, _ = load_fixture_parts()
    k = 5
    offset = sum(sizes[:k])
    garbage = b"\xff" * sizes[k]  # a varint that never terminates
    tel = fixture_telemetry(raw=raw[:offset] + garbage + raw[offset + sizes[k] :])
    assert len(tel) == 299
    assert tel.skipped == 1


def test_unknown_dji_schema_emits_warning():
    raw, pts, sizes, _ = load_fixture_parts()
    patched = raw.replace(b"dvtm_ac203.proto", b"dvtm_xx203.proto", 1)  # same length, other schema
    assert patched != raw
    with pytest.warns(UserWarning, match="dvtm_xx203.proto"):
        fixture_telemetry(raw=patched)
