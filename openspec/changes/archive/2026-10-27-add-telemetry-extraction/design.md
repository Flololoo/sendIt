# Design

## Context

This is a greenfield project. The only content so far is `videos/`, which holds three Osmo Action 4 clips. Each has an `.MP4` master and an `.LRF` proxy.

The clips were probed with ffprobe 8.1:

| Stream | Content |
|---|---|
| 0 | HEVC Main10, 3840×2160, 59.94 fps, display matrix rotation −90° |
| 1 | AAC stereo |
| 2 | `djmd` data stream ("DJI meta"), one packet per video frame |
| 3 | `tmcd` timecode |
| 4 | MJPEG cover image, 720×1280 |

The LRF has the same layout at 1280×720, 29.97 fps, H.264.

The `djmd` packets are protobuf, and the header identifies the schema as `dvtm_ac203.proto`. The first packet (262 B) also carries a device header and the stream configuration. Every later packet (about 123 B) carries only per-frame data.

The field layout below was observed by decoding all 150k records of the three clips. It is the reference for this change:

| Protobuf path | Meaning | Observed |
|---|---|---|
| `1.1.5` / `1.1.10` | Serial / model | `6S6VNCG00A0LN8`, `DJI OsmoAction4` |
| `1.1.2`, `1.1.6` | Version strings | firmware candidates; confirm during implementation |
| `2.3.1` / `2.3.2` / `2.3.3` | Width / height / fps | 3840 / 2160 / 59.94 |
| `3.1.1` | Camera frame counter | skips values (45,449 max vs 45,337 records) |
| `3.1.2` | Camera clock in µs | monotonic, not wall time |
| `3.2.2.1` | ISO (float) | 100 |
| `3.2.3.1` | Shutter denominator (float, 1/x s) | 100 to 4,090 |
| `3.2.5.1` | Digital zoom (inferred) | 1.0 |
| `3.2.6.1` | White balance in K (inferred) | 4,662 to 10,000 |
| `3.2.9.{1..4}` | Orientation quaternion, assumed (w, x, y, z) | unit norm, smooth (sensor-fused) |
| `3.2.10.{2,3,4}` | Accelerometer x, y, z in g | median magnitude 1.007 g, spikes to about 4 g |
| `3.2.11`, `3.2.12` | Empty submessages, presumed GPS slots | always empty |

Decoding is proto3, so fields at their default value can be absent. `3.2.10.1` is never present.

## Goals / Non-Goals

**Goals:**
- A dependency-light decoder that needs no `.proto` file and no protobuf library.
- One normalized telemetry model that the overlays consume.
- Extraction fast enough to run on import: seconds per clip, not minutes.

**Non-Goals:**
- Deriving lean angle or g-forces. Those belong to the overlay changes.
- Support for other cameras (GoPro GPMF, Insta360). The model is kept camera-agnostic so it can be added later.
- Reading GPS. The slot exists but there is no data to validate against.

## Decisions

### Project skeleton: a Python 3.12 package
- `app/` contains `telemetry/` for this change. Later changes add `workspace/`, `render/`, `overlays/` and `web/`.
- `pyproject.toml` declares the dependencies, with numpy at runtime and pytest for development.
- **Why:** Python 3.12 is already installed, and numpy suits the signal processing the overlays need.
- **Alternative:** Node, which is also installed. Rejected because its numeric and signal tooling is weaker.

### A minimal hand-written protobuf wire decoder
- It handles varint, fixed32, fixed64 and length-delimited fields, then maps the known paths from the table above into a sample.
- **Why:** There is no official `.proto` file. A generic wire decoder is about 40 lines, was already proven against all three clips, and tolerates unknown or new fields across firmware versions.
- **Alternative:** Reverse-engineering a `.proto` file for `protobuf` codegen. That is brittle across firmware versions and adds a dependency.

### Extraction through ffprobe and ffmpeg
- ffprobe lists the packets of the data stream with their `pts_time` and `size` (`-show_entries packet=pts_time,size`).
- ffmpeg dumps the raw stream (`-map 0:<djmd> -c copy -f data -`) to stdout.
- The decoder splits the dump by those sizes.
- **Why:** This reads only the small data stream and gives authoritative container timestamps.
- **Alternative:** Parsing the MP4 `stbl` boxes in Python. That would be faster, but it means writing more MP4 code ourselves. Revisit it only if extraction turns out to be slow.

### Timestamps from the container's pts, not from `3.1.1`/`3.1.2`
- The counter skips values, and the camera clock is not tied to the video timeline (requirement: Timeline alignment).

### The telemetry stream is located by handler name
- The decoder looks for the stream whose handler name is `DJI meta` or whose codec tag is `djmd`, instead of using a fixed index.

### Cache format and location
- Telemetry is cached as `.npz`: arrays `t`, `quat[N,4]`, `accel[N,3]`, `iso`, `shutter_s`, `wb_k`. A `meta.json` file sits next to it.
- The cache lives in `data/cache/<video-id>/`, and the cache key is the source path plus size plus mtime.
- **Why:** This is compact (about 7 MB uncompressed per 13-minute clip, less compressed) and loads instantly into numpy.

### Public API
- `get_telemetry(path) -> Telemetry`, where `Telemetry` exposes:
  - `samples` (numpy arrays)
  - `at(t)` (slerp for orientation, lerp for acceleration)
  - `meta`
- `export_csv(path, out)` writes the CSV export.

## Risks / Trade-offs

- **Field meaning is inferred, not documented.** This applies especially to the quaternion component order, white balance and zoom.
  → Fixture-based tests pin the observed ranges. The overlay changes include a check of orientation and sign against known curves in the footage.
- **DJI firmware updates could renumber fields.**
  → The decoder records the header's proto name and version in `meta`, and warns when it sees an unknown `dvtm_*` schema.
- **The test data is large.** The MP4s are 10 to 13 GB each.
  → Tests use small committed fixtures: a raw `djmd` dump plus a packet-size list for about 300 frames, cut from clip 0051. An optional integration test runs against `videos/` when the clips are present and is skipped otherwise.

## Open Questions

- Firmware version string: `1.1.6` decoded oddly (as a double). Confirm the correct field during implementation. It is informational only.
