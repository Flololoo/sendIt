"""Map DJI `djmd` records (dvtm_ac203.proto) onto telemetry fields.

Field paths were observed on Osmo Action 4 clips (see openspec design.md):

  1.1.1   proto schema name, e.g. "dvtm_ac203.proto"        (header packet only)
  1.1.5   camera serial number                              (header packet only)
  1.1.6   firmware version string, e.g. "10.00.42.03"       (header packet only)
  1.1.10  model name, e.g. "DJI OsmoAction4"                (header packet only)
  3.2.2.1 ISO (float)
  3.2.3.1 shutter denominator, exposure time = 1 / value (float)
  3.2.6.1 white balance in Kelvin (varint)
  3.2.9.1..4 orientation quaternion (w, x, y, z), float
  3.2.10.2..4 accelerometer x, y, z in g, float (3.2.10.1 is never present)
  3.2.11, 3.2.12  GPS slots; non-empty when a GPS remote was paired

Proto3 omits fields at their default value, so an absent quaternion or
accelerometer component reads as 0.0, while absent exposure fields read as NaN.
"""

from __future__ import annotations

from dataclasses import dataclass

from .protobuf import WIRE_FIXED32, WIRE_LEN, WIRE_VARINT, DecodeError, fields, submessage

KNOWN_SCHEMA = "dvtm_ac203.proto"
NAN = float("nan")


@dataclass(frozen=True)
class Record:
    quat: tuple[float, float, float, float]  # w, x, y, z
    accel: tuple[float, float, float]  # x, y, z in g
    iso: float
    shutter_s: float
    wb_k: float
    gps: bool


def split_packets(raw: bytes, sizes) -> list[bytes]:
    """Cut the concatenated data-stream payload into per-packet records."""
    total = sum(int(s) for s in sizes)
    if total != len(raw):
        raise ValueError(f"packet sizes add up to {total} bytes but the payload is {len(raw)} bytes")
    out = []
    pos = 0
    for size in sizes:
        out.append(raw[pos : pos + int(size)])
        pos += int(size)
    return out


def _float_field(msg: dict, number: int, default: float) -> float:
    entry = msg.get(number)
    if entry is None:
        return default
    wire, value = entry
    if wire != WIRE_FIXED32:
        raise DecodeError(f"field {number} is not a fixed32 float")
    return value


def _varint_field(msg: dict, number: int) -> int | None:
    entry = msg.get(number)
    if entry is None:
        return None
    wire, value = entry
    if wire != WIRE_VARINT:
        raise DecodeError(f"field {number} is not a varint")
    return value


def _text_field(msg: dict, number: int) -> str | None:
    entry = msg.get(number)
    if entry is None:
        return None
    wire, value = entry
    if wire != WIRE_LEN:
        raise DecodeError(f"field {number} is not a string")
    return value.decode("utf-8", errors="replace").strip() or None


def decode_record(buf: bytes) -> Record:
    """Decode one per-frame record. Raises DecodeError if it is malformed or incomplete."""
    sensor = submessage(fields(buf).get(3)).get(2)
    if sensor is None:
        raise DecodeError("record has no sensor block (3.2)")
    block = submessage(sensor)
    if 9 not in block or 10 not in block:
        raise DecodeError("record lacks orientation (3.2.9) or accelerometer (3.2.10)")

    quat_msg = submessage(block[9])
    accel_msg = submessage(block[10])
    quat = tuple(_float_field(quat_msg, n, 0.0) for n in (1, 2, 3, 4))
    accel = tuple(_float_field(accel_msg, n, 0.0) for n in (2, 3, 4))

    iso = _float_field(submessage(block.get(2)), 1, NAN)
    shutter_denom = _float_field(submessage(block.get(3)), 1, NAN)
    wb = _varint_field(submessage(block.get(6)), 1)
    gps = any(
        entry is not None and entry[0] == WIRE_LEN and len(entry[1]) > 0
        for entry in (block.get(11), block.get(12))
    )
    return Record(
        quat=quat,
        accel=accel,
        iso=iso,
        shutter_s=1.0 / shutter_denom if shutter_denom > 0 else NAN,
        wb_k=float(wb) if wb is not None else NAN,
        gps=gps,
    )


def decode_header(buf: bytes) -> dict:
    """Read the device header (1.1.*) from the first packet of a clip."""
    device = submessage(submessage(fields(buf).get(1)).get(1))
    return {
        "proto_schema": _text_field(device, 1),
        "serial": _text_field(device, 5),
        "firmware": _text_field(device, 6),
        "model": _text_field(device, 10),
    }
