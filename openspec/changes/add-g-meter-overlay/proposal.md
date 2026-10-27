# Proposal

## Why

Braking, accelerating and road quality are part of every ride, but they are invisible in the footage. The camera's accelerometer records them at 59.94 Hz. In clip 0051 it shows spikes of 2 to 4 g on bumps and sustained shifts when braking. A g-meter makes smooth (or not so smooth) riding visible. Bump call-outs ("BUMP 1.4 g") add a fun, relatable beat, and the bump counter feeds the "roads in my area" kind of content.

## What Changes

- A new overlay, `gmeter` ("G-meter & bumps"), registered with the overlay engine. It has one toggle in the UI, and its parts can be switched on and off with settings.
- It computes the acceleration of the rider and bike, with gravity removed, using the camera orientation. The result is split into:
  - forward/backward (accelerating or braking)
  - left/right (cornering)
  - vertical (bumps)
  
  These are relative to the direction of travel, which is estimated from the camera's heading and depends on the clip's mount.
- **G-meter:** a circle diagram with a dot for the current horizontal g-force, a short trail, rings at 0.5 g and 1.0 g, and a numeric total.
- **Bump detection:**
  - short vertical acceleration events, with sensitivity low, medium or high
  - a "BUMP" call-out that shows the peak g and fades out
  - an optional bump counter for the exported range

## Capabilities

### New Capabilities
- `g-meter-overlay`: Deriving horizontal g-forces and bump events from accelerometer and orientation telemetry, and displaying them as a g-meter with bump call-outs.

### Modified Capabilities
<!-- none -->

## Impact

- New module `app/overlays/gmeter.py`, which reuses the orientation-convention helper from `add-lean-angle-overlay` (`gravity_in_camera`).
- No new dependencies.
- Depends on `add-telemetry-extraction`, `add-overlay-rendering` (including the clip mount in `ClipContext`) and `add-lean-angle-overlay` (the verified quaternion convention).
