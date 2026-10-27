"""Minimal protobuf wire-format decoder.

Handles varint, fixed64, length-delimited and fixed32 fields. No .proto file or
protobuf library is needed. Fields are returned as (wire_type, value) where
varints are int, fixed64 is float (double), fixed32 is float (single) and
length-delimited is bytes. Nested messages are decoded by calling `fields` again
on the bytes.
"""

from __future__ import annotations

import struct

WIRE_VARINT = 0
WIRE_FIXED64 = 1
WIRE_LEN = 2
WIRE_FIXED32 = 5


class DecodeError(ValueError):
    """Raised for truncated or malformed protobuf data."""


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise DecodeError("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise DecodeError("varint too long")


def fields(buf: bytes) -> dict[int, tuple[int, object]]:
    """Decode one message level into {field_number: (wire_type, value)}.

    A repeated field keeps its last occurrence, which matches protobuf's rule for
    scalar fields. Raises DecodeError if any part of the buffer is malformed.
    """
    result: dict[int, tuple[int, object]] = {}
    pos = 0
    end = len(buf)
    while pos < end:
        key, pos = _varint(buf, pos)
        number = key >> 3
        wire = key & 7
        if number == 0:
            raise DecodeError("field number 0")
        if wire == WIRE_VARINT:
            value, pos = _varint(buf, pos)
        elif wire == WIRE_FIXED64:
            if pos + 8 > end:
                raise DecodeError("truncated fixed64")
            value = struct.unpack_from("<d", buf, pos)[0]
            pos += 8
        elif wire == WIRE_LEN:
            length, pos = _varint(buf, pos)
            if pos + length > end:
                raise DecodeError("truncated length-delimited field")
            value = bytes(buf[pos : pos + length])
            pos += length
        elif wire == WIRE_FIXED32:
            if pos + 4 > end:
                raise DecodeError("truncated fixed32")
            value = struct.unpack_from("<f", buf, pos)[0]
            pos += 4
        else:
            raise DecodeError(f"unsupported wire type {wire}")
        result[number] = (wire, value)
    return result


def submessage(entry: tuple[int, object] | None) -> dict[int, tuple[int, object]]:
    """Decode a length-delimited entry from `fields` as a nested message.

    Returns an empty dict for a missing entry.
    """
    if entry is None:
        return {}
    wire, value = entry
    if wire != WIRE_LEN:
        raise DecodeError("expected a length-delimited (message) field")
    return fields(value)
