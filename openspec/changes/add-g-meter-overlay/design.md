# Design

## Context

Telemetry gives the raw 3-axis accelerometer in g, which includes gravity, and the fused orientation quaternion, both at 59.94 Hz. In clip 0051:
- |a| has a median of 1.007 g and a 99th percentile of 1.37 g, with isolated spikes up to about 4 g.
- The individual axes show strong engine and road vibration.

`add-lean-angle-overlay` delivers `gravity_in_camera(quat)`, with the quaternion convention verified against the accelerometer. The overlay contract, `ClipContext.mount` and the per-overlay `validate` hook come from `add-overlay-rendering`.

## Goals / Non-Goals

**Goals:**
- Physically meaningful horizontal g-forces that a viewer can read at a glance.
- Bump detection that triggers on noticeable hits, not on engine vibration.

**Non-Goals:**
- Exact vehicle dynamics. Without GPS speed there is no cross-check with speed derivatives.
- A timeline of bump markers in the UI, or exporting the bump list. This is a possible follow-up change that would modify `overlay-controls`.

## Decisions

### Remove gravity in the camera frame, then project
- `a_lin_cam = a_cam − g_cam`, where `g_cam` is world-up expressed in the camera frame. Its sign convention is matched to the accelerometer reading of about +1 g at rest.
- Rotate `a_lin_cam` into the world frame. Vertical = the world-z component.
- Horizontal: project onto the travel basis. Forward is the camera's viewing axis projected onto the horizontal plane, then smoothed. Lateral = up × forward, with the sign chosen so that right is positive.
- **Why:** The orientation is fused and smooth, so subtracting it isolates the linear acceleration even while leaning. In a coordinated turn, the raw accelerometer of a bike-mounted camera points along the bike's axis, and only the orientation-based decomposition turns that into lateral g.
- **Cross-check:** In a steady curve, |lateral| ≈ tan(|lean|). A verification task compares these for the bike mount.

### Smoothing the travel direction
- Smooth the horizontal forward unit vector (not the angle, which avoids wrap-around) with a centred window: 0.5 s for bike, 2.5 s for helmet.
- For helmet, also cap the forward vector's rate of rotation at 45°/s, which suppresses glances.

### Filtering
- **Meter:** a zero-phase low-pass on the longitudinal and lateral components, as a 0.4 s centred Hann window. Vibration from the engine and road is well above 5 Hz and averages out.
- **Bumps:** take the vertical component, remove the slow trend (subtract a 1.0 s centred moving average), and take the magnitude of the residual. Then find peaks:
  - with a 1.0 s merge window
  - keeping the largest peak in each window

### Sensitivity thresholds
- Starting values, applied to the residual peak: low 1.2 g, medium 0.8 g, high 0.5 g.
- One shared detector at the lowest threshold, filtered per level. This guarantees the subset property in the spec, because the peaks are found once and only the threshold differs.
- The values are tuned against the footage in the tasks. Tuning changes only the constants, not the behaviour in the spec.

### Precompute in `prepare`
- `prepare` precomputes, over the whole clip:
  - the smoothed longitudinal and lateral series
  - the bump events: list of (t, peak_g)
  - the cumulative bump count from the range start
- `draw(t)` looks up the nearest sample, the trail (the last 1 s of samples, decimated to about 15 points) and the most recent event within 1.5 s.

### Drawing
- `base_box` is 300×360 px at 1080 width.
- The circle has a radius scaled to 1.2 g, with the rings labelled. There is a dot, a fading trail, the value text below, and the counter "Bumps: N" with a small road-bump icon.
- The bump call-out is a badge in the accent colour, drawn inside the overlay's own box, above the meter. When `show_meter` is off, the box shrinks to the call-out and counter area.
- The default position is middle-right, which keeps it away from the lean gauge (top-left) and inside the safe area.

### Validation
- `validate()` returns an error when `show_meter` and `show_bumps` are both false. This uses the overlay hook from the engine.

## Risks / Trade-offs

- **Accelerometer clipping or aliasing at 59.94 Hz.** Engine vibration can alias into low frequencies.
  → Filtering over windows of 0.4 s or more, and the thresholds tuned on real clips. If false bumps persist, add a minimum event duration of 2 samples or more.
- **On a helmet mount, the rider's body absorbs bumps**, so they read lower than on a bike mount.
  → The user picks the sensitivity level per clip. A higher sensitivity is suggested for the helmet in the setting description.
- **Accelerometer bias of about 0.007 g at rest.**
  → It is negligible against the 0.05 g requirement. If needed, subtract the median of the straight segments, the same way lean is calibrated.

## Implementation notes

- **Frame handedness:** the quaternion world frame has +z pointing down, so right of the heading is `(-f_y, f_x)`. Verified on the whole of clip 0051 (the 5 s fixture is too short to pin the sign).
- **Lean cross-check (4.1, bike mount, 4543 steady-curve samples):** corr(lateral, tan(lean)) = +0.98 after the sign fix, corr(|lateral|, |tan(lean)|) = 0.74, median |lateral| / |tan(lean)| = 0.78. The curves follow each other; lateral g reads about 25% low (0.4 s smoothing, tyre width, lean noise).
- **Longitudinal sign:** positive when pulling away (58–66 s) and negative when approaching the final stop (740–749 s). Clip 0051 has no hard braking, so this is weak evidence.
- **Bump counts on clip 0051 (756 s) at the starting thresholds:** low 9, medium 29, high 62 events. The top-20 medium list is dense around 360–520 s (rough road). Thresholds are not yet tuned (task 2.2).
- **Meter off:** the box is fixed by the overlay contract, so the box keeps its size and only the call-out and counter area (top 96 px) is drawn.
