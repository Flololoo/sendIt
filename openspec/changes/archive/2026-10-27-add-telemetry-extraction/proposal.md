# Proposal

## Why

The DJI Osmo Action 4 clips in `videos/` carry a per-frame telemetry track (`djmd`, "DJI meta"). It holds the camera orientation (as a quaternion), a 3-axis accelerometer and exposure data. Nothing in the project can read it yet. The lean-angle and g-meter overlays, and anything built later, need this data decoded, aligned to the video timeline and cached. Doing that once, in a shared layer, keeps each overlay from parsing the protobuf itself.

## What Changes

- Detect the DJI meta track in an MP4 or LRF file and decode every per-frame record (protobuf `dvtm_ac203.proto`) into structured samples:
  - orientation quaternion
  - accelerometer in g
  - ISO, shutter and white balance
- Align each sample to the video presentation timeline and support lookup at any timestamp, with interpolation.
- Extract clip-level recording metadata:
  - camera model, serial and firmware
  - resolution, frame rate and display rotation
  - UTC start time and duration
  - whether GPS is present
- Cache the decoded telemetry next to the app's workspace data so repeated use is instant, and invalidate the cache when the source file changes.
- Export telemetry as CSV for debugging and for use in external tools.
- Report GPS as unavailable for the current footage. The GPS slots are empty because no DJI GPS remote was paired. Speed-based features are therefore out of scope.

## Capabilities

### New Capabilities
- `telemetry-extraction`: Reads DJI Osmo Action telemetry and recording metadata from video files and serves time-aligned samples to the rest of the system.

### Modified Capabilities
<!-- none: greenfield project -->

## Impact

- New Python package module for telemetry (no code exists yet; this change also lays down the project skeleton and test setup).
- Runtime dependency on `ffmpeg`/`ffprobe` on PATH (already installed via winget, ffmpeg 8.1) and `numpy`.
- This change has no dependencies. The changes that depend on it are `add-video-workspace`, `add-overlay-rendering`, `add-lean-angle-overlay` and `add-g-meter-overlay`.
