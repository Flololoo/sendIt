# Tasks

## 1. Acceleration decomposition

- [x] 1.1 Implement gravity removal and the world-frame rotation, using `gravity_in_camera` from the lean module. Verify that a test on the at-rest start of the telemetry fixture gives components within ±0.05 g after the 0.4 s low-pass.
- [x] 1.2 Implement the travel-direction estimate: horizontal forward vector, mount-specific smoothing, and the helmet rate cap. Verify that a synthetic test (straight motion plus a 60° head glance for 0.5 s) keeps the smoothed heading within 5° for helmet.
- [x] 1.3 Project onto longitudinal and lateral with the signs pinned (braking negative, right positive). Verify a synthetic test with a known deceleration and a known right turn.

## 2. Bump detection

- [x] 2.1 Implement the detrended vertical residual, the shared peak detection with the 1 s merge, and the per-sensitivity thresholds. Verify unit tests: a double hit 0.3 s apart gives one event with the max peak, a smooth signal gives no events, and the low ⊆ medium ⊆ high subset property holds.
- [ ] 2.2 Tune the thresholds on the footage. List the top 20 medium-sensitivity events of clip 0051, watch each one, and adjust the constants until at least 16 of 20 are real bumps. Record the final values and the hit rate in `design.md`.

## 3. Overlay

- [x] 3.1 Implement `GMeterOverlay`: settings, the `validate` rule (at least one of meter or bumps), and `prepare`, which builds the series, the events and the cumulative count from the range start. Register it. Verify unit tests that both-off is rejected and that the count is 0 at the range start.
- [x] 3.2 Implement `draw`: circle, rings, dot and trail, clamping at 1.2 g, the value text, the call-out with the 1.0 s hold and 0.5 s fade, and the counter. The box shrinks when the meter is off. Verify golden-image tests for braking at −0.4 g, mid-call-out, mid-fade and meter-off.

## 4. End-to-end check

- [x] 4.1 Cross-check against the lean overlay. Over a steady curve in clip 0051 with the bike mount (or the matching mount), compare |lateral g| with tan(|lean|), and record the agreement in the change notes. Verify that the curves follow each other visibly.
- [x] 4.2 Export 0051 from 300 to 330 s with `lean` and `gmeter` both enabled, at the social preset. Confirm that the overlays do not overlap, that both stay in the safe area, that the bump at about 324 s gets a call-out, and that braking moves the dot down.
- [x] 4.3 Add a "G-meter & bumps" section to `README.md`: what is measured, what the sensitivity levels mean, and the helmet versus bike notes.
