# Tasks

## 1. Orientation convention

- [x] 1.1 Implement `gravity_in_camera(quat, convention)` for the candidate conventions (q or q⁻¹, × wxyz or xyzw). Verify with unit tests on synthetic quaternions of known rotations.
- [x] 1.2 Implement the convention check: correlate `g_cam` with the 2-second low-pass of the raw accelerometer, and pick the best match. Verify that a test on the committed telemetry fixture selects one convention with a mean angular error under 5°, and record the chosen convention in the code.

## 2. Lean signal

- [x] 2.1 Implement the roll computation in the sensor plane, plus the heading rate. Verify that a unit test with a synthetic rotation about the viewing axis returns the input angle.
- [x] 2.2 Implement the automatic upright reference (straight segments, circular median, fallback) and the offset and clamp. Verify unit tests on a synthetic series: a straight segment reads 0 ±0.5°, there is a fallback when straight riding totals under 10 s, an 80° input is clamped to 65°, and the offset is additive.
- [x] 2.3 Implement zero-phase smoothing chosen by `ClipContext.mount`. Verify a test that the helmet series has lower frame-to-frame variance than the bike series, and that the peak times match within 0.1 s.
- [x] 2.4 Pin the sign against the footage: watch clip 0051, note one right-hand and one left-hand curve timestamp (one candidate is around 304 s), and add them as integration-test fixtures (skipped without `videos/`). Verify the test shows the right curve > 0 and the left curve < 0, and a straight segment within ±3°.

## 3. Overlay

- [x] 3.1 Bundle an open-licence font (for example Inter or Barlow, OFL) in `app/overlays/assets/` with its licence file. Verify that the font loads in Pillow.
- [x] 3.2 Implement `LeanOverlay` (settings, `prepare` with the running max and min from the range start, `draw` with the gauge, value text and max marks) and register it. Verify unit tests that `draw` at a −17.6° sample shows "L 18°" (check through a text-layout helper), and that with `show_max` off no max text is drawn.
- [x] 3.3 Add golden-image tests: render the overlay layer at three fixed sample values and compare with the committed PNGs (pixel-exact). Verify the tests pass, and document how to regenerate the goldens.

## 4. End-to-end check

- [x] 4.1 Through the UI or the CLI, export 0051 from 300 to 330 s with `lean` (with the clip mount set to match the footage) at the social preset. Watch the result and confirm that the needle direction matches the curves, that the value is near 0 on straights, and that the max builds up. Record what you observed, and the mount used, in the change notes.
- [x] 4.2 Add a short "Lean angle" section to `README.md`: how it is computed, what the helmet mode limitation is, and when to use the offset slider.
