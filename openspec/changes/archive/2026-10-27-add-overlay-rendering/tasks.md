# Tasks

## 1. Overlay contract and registry

- [x] 1.1 Add the Pillow dependency and create `app/overlays/` with `Overlay`, `Setting`, `Position`, `Size` and `ClipContext` (including `mount`, defaulting to `bike`) types. Verify that `pip install -e .` succeeds and that a unit test asserts the default mount is `bike`.
- [x] 1.2 Implement the registry: register, list, and availability for each clip (no telemetry → unavailable, with a reason). Verify unit tests using a test-only `TimestampOverlay` registered in `tests/`.
- [x] 1.3 Implement configuration validation (unknown overlay or setting, out-of-range values, defaults filled in, the overlay's optional `validate` hook). Verify unit tests show that each error message names the offending field.

## 2. Layout

- [x] 2.1 Implement the preset → bounding box function with the S/M/L scaling and the safe-area insets. Verify tests that every preset box lies inside the safe area at 1080×1920 and 2160×3840, with identical relative geometry.
- [x] 2.2 Implement stacking for shared presets. Verify that a test with two overlays at top-left asserts the boxes do not intersect.
- [x] 2.3 Implement the overlay layer renderer: one RGBA image cropped to the union box, drawn by calling each overlay's `draw`. Verify that a test renders the same `t` twice and gets byte-identical images.

## 3. Preview

- [x] 3.1 Implement frame grabbing for `t`, preferring the LRF, with auto-rotation to portrait. Verify that a test against clip 0051, skipped without `videos/`, returns a portrait 720-wide image.
- [x] 3.2 Implement `preview(clip, t, cfg, guides)`, compositing the overlay layer and, optionally, the safe-area guides. Verify that a test shows the guides appear only when they are requested.

## 4. Export pipeline

- [x] 4.1 Probe the encoders at startup (hevc_nvenc, then h264_nvenc, then libx264). Verify that a unit test with a mocked probe picks the right fallback, and log the chosen encoder.
- [x] 4.2 Implement pass 1: pipe the overlay layer to an ffmpeg alpha `.mov`. Verify that a test on a 3-second range produces a file whose frame count equals 3 s × 59.94 fps (±1).
- [x] 4.3 Implement pass 2: decode, rotate, scale to the preset, composite, encode (8-bit, AAC, faststart). Verify that ffprobe on the output of a 3-second test reports the expected resolution, fps, codecs and pix_fmt `yuv420p`.
- [x] 4.4 Validate the range and seek to it accurately. Verify that a test rejects an invalid range, and that the output of a 300–330 s export lasts 30 s ±1 frame.
- [x] 4.5 Implement output naming with collision suffixes. Verify that a unit test covers a repeated export.

## 5. Jobs

- [x] 5.1 Implement `ExportQueue`: one worker, FIFO, the job states, progress from `-progress pipe:1`, and the ETA. Verify tests show a second job queues behind the first, and that progress is monotonic and ends at 100%.
- [x] 5.2 Implement cancellation and failure handling: kill ffmpeg, delete the temporary and partial files, and give human-readable reasons. Verify tests for cancel mid-render and for a simulated missing ffmpeg.
- [x] 5.3 Add the CLI `python -m app.render export …`. Verify it by exporting 0051 from 300 to 330 s with the test overlay and the social preset, then open the result and confirm it plays with the overlay visible.

## 6. Performance check

- [x] 6.1 Benchmark a 30-second export at the original and social presets on this machine, and record the timings and the chosen encoder in `README.md`. Verify the social preset finishes in under 3 minutes.
