# Tasks

## 1. Project skeleton

- [x] 1.1 Create `pyproject.toml` (Python ≥3.12, runtime dep `numpy`, dev dep `pytest`) and the `app/` and `app/telemetry/` packages. Verify that `pip install -e .[dev]` succeeds and `pytest` runs and collects 0 tests.
- [x] 1.2 Add an ffmpeg/ffprobe availability check with a clear error message. Verify it with a unit test that simulates a missing binary.
- [x] 1.3 Add a `README.md` with setup steps (Python, ffmpeg via winget, editable install). Verify the steps by following them in a fresh venv.

## 2. Test fixtures

- [x] 2.1 Write a `scripts/make_fixture.py` that dumps the first 300 `djmd` packets and their pts and sizes from a clip into `tests/fixtures/`. Run it on clip 0051 and verify the fixture files are smaller than 100 KB and committed.

## 3. Decoder

- [x] 3.1 Implement the protobuf wire decoder (varint, fixed32, fixed64, length-delimited). Verify it with unit tests on hand-built byte strings, including a truncated message.
- [x] 3.2 Map the decoded paths to sample fields (quaternion, accel, ISO, shutter as seconds, WB) and the header fields to metadata. Verify a fixture test asserts |accel| ≈ 1 g at the start of the clip, the quaternion norm ≈ 1, ISO 100 and shutter 1/250 s on the first frame.
- [x] 3.3 Skip and count undecodable records. Verify a test that corrupts one fixture record yields N−1 samples and `skipped == 1`.

## 4. Extraction and alignment

- [x] 4.1 Locate the DJI meta stream by handler or codec tag, and read packet pts and sizes through ffprobe and the raw data through ffmpeg. Verify that a test on a non-DJI clip (generated with `ffmpeg -f lavfi -i testsrc -t 1`) reports no telemetry and does not error.
- [x] 4.2 Build timestamps from container pts, relative to the start of the video. Verify the fixture test: the first timestamp is 0.0, the timestamps are monotonic, and the spacing is about 1/59.94 s.
- [x] 4.3 Implement `Telemetry.at(t)` with slerp, lerp and clamping. Verify unit tests for midpoint, before-start and after-end.
- [x] 4.4 Extract recording metadata: model, serial, firmware, resolution, fps, rotation, display size and orientation, UTC start, duration, GPS availability. Verify that a test on the fixture header reports 2160×3840 portrait and GPS unavailable.

## 5. Cache and export

- [x] 5.1 Implement the `.npz` + `meta.json` cache under `data/cache/<video-id>/`, invalidated by size and mtime. Verify tests show that a second call does not invoke ffmpeg, and that touching the source triggers re-extraction.
- [x] 5.2 Implement CSV export. Verify a test checks the header columns and that the row count equals the sample count.
- [x] 5.3 Add a CLI entry point, `python -m app.telemetry <file> [--csv out.csv]`, that prints the metadata. Verify it runs against `videos/DJI_20261026155823_0051_D.MP4`, reports 45,337 samples, and finishes in under 60 s.

## 6. Integration check

- [x] 6.1 Add an integration test, skipped when `videos/` is absent, that extracts all three clips. Verify each sample count matches the ffprobe `nb_frames` of the data stream (45,337 / 47,618 / 57,093).
