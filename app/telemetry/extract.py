"""Turn a clip's data stream into a Telemetry object."""

from __future__ import annotations

import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from . import ffmpeg_io
from .decoder import KNOWN_SCHEMA, DecodeError, decode_header, decode_record, split_packets
from .model import Metadata, Samples, Telemetry


def build_metadata(
    summary: dict,
    header: dict,
    *,
    source: str,
    telemetry_available: bool,
    has_gps: bool,
) -> Metadata:
    """Combine ffprobe's video summary with the DJI header into clip metadata."""
    width, height = summary["width"], summary["height"]
    rotation = int(summary["rotation"])
    if rotation % 180 == 90:  # -90 / 90 / 270 turn the picture on its side
        display_width, display_height = height, width
    else:
        display_width, display_height = width, height
    start = summary.get("creation_time")
    start_utc = datetime.fromisoformat(start).astimezone(UTC).isoformat() if start else None
    return Metadata(
        source=source,
        telemetry_available=telemetry_available,
        proto_schema=header.get("proto_schema"),
        model=header.get("model"),
        serial=header.get("serial"),
        firmware=header.get("firmware"),
        width=width,
        height=height,
        fps=summary.get("fps"),
        rotation=rotation,
        display_width=display_width,
        display_height=display_height,
        orientation="portrait" if display_height > display_width else "landscape",
        duration_s=float(summary["duration_s"]),
        start_utc=start_utc,
        has_gps=has_gps,
    )


def build_telemetry(
    raw: bytes,
    pts_s,
    sizes,
    summary: dict,
    *,
    source: str,
) -> Telemetry:
    """Decode a raw djmd payload into a Telemetry.

    `pts_s` and `sizes` are the container timing of each packet, in file order.
    Timestamps are the packet pts minus the video's start time, so the first
    record of a clip lands at 0.0.
    """
    pts = np.asarray(pts_s, dtype=np.float64)
    packets = split_packets(raw, sizes)
    if len(pts) != len(packets):
        raise ValueError("pts and sizes lists have different lengths")

    header: dict = {}
    if packets:
        try:
            header = decode_header(packets[0])
        except DecodeError:
            header = {}
    schema = header.get("proto_schema")
    if schema and schema.startswith("dvtm_") and schema != KNOWN_SCHEMA:
        warnings.warn(f"unknown DJI telemetry schema {schema!r}; decoded fields may be wrong", stacklevel=2)

    t_rel = pts - float(summary.get("start_time_s", 0.0))
    times, quats, accels, isos, shutters, wbs = [], [], [], [], [], []
    skipped = 0
    has_gps = False
    for i, buf in enumerate(packets):
        try:
            rec = decode_record(buf)
        except DecodeError:
            skipped += 1
            continue
        times.append(t_rel[i])
        quats.append(rec.quat)
        accels.append(rec.accel)
        isos.append(rec.iso)
        shutters.append(rec.shutter_s)
        wbs.append(rec.wb_k)
        has_gps = has_gps or rec.gps

    samples = Samples(
        t=np.asarray(times, dtype=np.float64),
        quat=np.asarray(quats, dtype=np.float64).reshape(-1, 4),
        accel=np.asarray(accels, dtype=np.float64).reshape(-1, 3),
        iso=np.asarray(isos, dtype=np.float64),
        shutter_s=np.asarray(shutters, dtype=np.float64),
        wb_k=np.asarray(wbs, dtype=np.float64),
    )
    meta = build_metadata(summary, header, source=source, telemetry_available=True, has_gps=has_gps)
    return Telemetry(samples=samples, meta=meta, skipped=skipped)


def extract_telemetry(path: str | Path) -> Telemetry:
    """Read the telemetry track of a video with ffprobe and ffmpeg.

    A file without a DJI meta track gives an empty Telemetry, not an error.
    """
    ffmpeg_io.require_ffmpeg()
    path = Path(path)
    info = ffmpeg_io.probe(path)
    summary = ffmpeg_io.video_summary(info)
    index = ffmpeg_io.find_telemetry_stream(info)
    if index is None:
        meta = build_metadata(summary, {}, source=path.name, telemetry_available=False, has_gps=False)
        return Telemetry(samples=Samples.empty(), meta=meta, skipped=0)
    pts, sizes = ffmpeg_io.read_packet_times_and_sizes(path, index)
    raw = ffmpeg_io.read_raw_packets(path, index)
    return build_telemetry(raw, pts, sizes, summary, source=path.name)
