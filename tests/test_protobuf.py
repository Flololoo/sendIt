import struct

import pytest

from app.telemetry.protobuf import DecodeError, fields, submessage


def test_varint_single_and_multi_byte():
    # field 1 = 150 (0x96 0x01), field 2 = 1
    assert fields(b"\x08\x96\x01\x10\x01") == {1: (0, 150), 2: (0, 1)}


def test_varint_max_64_bit():
    buf = b"\x08" + b"\xff" * 9 + b"\x01"
    assert fields(buf) == {1: (0, (1 << 64) - 1)}


def test_fixed32_is_little_endian_float():
    buf = b"\x15" + struct.pack("<f", 100.0)  # field 2, wire type 5
    wire, value = fields(buf)[2]
    assert wire == 5
    assert value == pytest.approx(100.0)


def test_fixed64_is_double():
    buf = b"\x09" + struct.pack("<d", 0.25)  # field 1, wire type 1
    assert fields(buf) == {1: (1, 0.25)}


def test_length_delimited_bytes_and_string():
    buf = b"\x0a\x05hello"  # field 1, length 5
    assert fields(buf) == {1: (2, b"hello")}


def test_nested_message():
    inner = b"\x08\x07"  # field 1 = 7
    buf = b"\x12" + bytes([len(inner)]) + inner  # field 2, message
    outer = fields(buf)
    assert outer[2][0] == 2
    assert fields(outer[2][1]) == {1: (0, 7)}


def test_empty_message():
    assert fields(b"") == {}
    assert submessage(fields(b"\x12\x00")[2]) == {}


def test_submessage_missing_entry_is_empty():
    assert submessage(None) == {}


def test_submessage_wrong_wire_type_raises():
    with pytest.raises(DecodeError):
        submessage((0, 5))


def test_truncated_length_delimited_raises():
    buf = b"\x0a\x05abc"  # claims 5 bytes, only 3 present
    with pytest.raises(DecodeError):
        fields(buf)


def test_truncated_varint_raises():
    with pytest.raises(DecodeError):
        fields(b"\x08\x96")


def test_truncated_fixed32_raises():
    with pytest.raises(DecodeError):
        fields(b"\x15\x00\x00")


def test_truncated_fixed64_raises():
    with pytest.raises(DecodeError):
        fields(b"\x09\x00\x00\x00")


def test_truncated_nested_message_raises_when_decoded():
    inner = b"\x08\x07\x10\x01"
    buf = b"\x12" + bytes([len(inner)]) + inner[:3]  # outer length says 4, only 3 present
    with pytest.raises(DecodeError):
        fields(buf)


def test_group_wire_type_is_rejected():
    with pytest.raises(DecodeError):
        fields(b"\x0b")  # field 1, start group


def test_field_number_zero_is_rejected():
    with pytest.raises(DecodeError):
        fields(b"\x00\x01")
