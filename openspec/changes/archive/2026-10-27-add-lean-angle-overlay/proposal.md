# Proposal

## Why

Lean angle is the most telling number for motorcycle footage. For a channel about learning to ride, "how far did I actually lean" is relatable, honest content: progress shows over time, and modest angles are fine. The camera's sensor-fused orientation already holds this signal. In clip 0051, the camera roll swings about ±20° in curves, in step with heading changes. Showing it needs calibration, because the camera is mounted sometimes on the helmet and sometimes on the bike, plus a clear gauge.

## What Changes

- A new overlay, `lean`, registered with the overlay engine. It appears in the UI automatically.
- It computes a signed lean angle (left or right) from the orientation quaternion, as roll about the camera's viewing direction, relative to an upright reference.
- **Smoothing tuned to the clip's camera mount** (helmet or bike). The mount is set per clip on the clip screen, as defined in `add-overlay-rendering` and `add-video-workspace`.
- **Automatic upright calibration** from segments of straight riding. A manual offset slider covers the remaining correction.
- **Gauge:**
  - a semicircular scale with a tilting needle or bike marker
  - the current value in whole degrees, with L/R
  - optional running maximum left and right within the exported range
  - legible over bright sky and dark road

## Capabilities

### New Capabilities
- `lean-angle-overlay`: Computing, calibrating and displaying the rider's lean angle from camera orientation telemetry.

### Modified Capabilities
<!-- none -->

## Impact

- New module `app/overlays/lean.py`, plus signal helpers.
- No new dependencies (numpy, Pillow).
- Depends on `add-telemetry-extraction` and `add-overlay-rendering`. It becomes visible in the UI through `add-video-workspace`.
