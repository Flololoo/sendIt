# Design

## Context

Telemetry provides a sensor-fused unit quaternion per frame at 59.94 Hz (`Telemetry.samples.quat`) and the raw accelerometer in g.

An exploratory decode of clip 0051, with a naive ZYX Euler conversion, gave:
- "roll": median 96° (the camera is in portrait, so about 90° of that is mounting)
- spread from the 1st to 99th percentile: 74.5° to 117.9°
- "pitch": constant at about −12° (mount tilt)
- "yaw": swings by tens of degrees through turns

Around 300 to 306 s, the roll dropped by about 21° while the yaw fell from 100° to 62°, which is a curve. The quaternion is smooth. The raw accelerometer is dominated by vibration and cannot be used for lean on its own.

The overlay contract (`prepare` / `draw`) and the layout come from `add-overlay-rendering`.

## Goals / Non-Goals

**Goals:**
- A lean signal that is robust to the order and conventions of the DJI quaternion, which is undocumented.
- Calibration that needs no user action in the normal case.

**Non-Goals:**
- True bike lean from a helmet mount. Head tilt cannot be separated from bike lean without a second sensor. Helmet mode is an approximation, and it typically under-reads, because riders keep their heads more level than the bike.
- Physics-based lean (atan(v·ω/g)). That needs speed, and there is no GPS.

## Decisions

### Compute lean from the gravity direction in the camera frame, not from Euler angles
- Rotate world-up into the camera frame: `g_cam = q⁻¹ ⊗ (0,0,1) ⊗ q`.
- Take `roll = atan2(g_cam·x̂, g_cam·ŷ)` in the sensor plane, which is perpendicular to the viewing axis.
- **Why:** This needs only two facts: which sensor axes span the image plane, and whether the quaternion maps camera→world or world→camera. Euler decomposition depends on the axis order and on the gimbal-lock region, which is exactly where the portrait mount sits (about 90°).
- **Verifying the convention:** Over long windows of 2 s or more, the mean of the raw accelerometer equals gravity in the camera frame. The correct convention (q or q⁻¹, and the component order) is the one whose `g_cam` matches the low-pass-filtered accelerometer direction best over the whole clip. This is a unit-testable criterion, and it is checked once against the real clips.
- **Alternative:** Use the naive Euler "roll", which looked right in the exploration. Rejected because of its fragility near 90°.

### The sign convention is pinned against footage
- After the convention is fixed, the sign is chosen so that a known right-hand curve in clip 0051 gives a positive value. A task identifies one right-hand and one left-hand curve timestamp by watching the footage, and those become regression fixtures.

### Automatic upright reference
- Compute the heading rate from the yaw of the camera's forward axis in the world frame.
- "Straight" means samples where |heading rate| < 2°/s for at least 3 s.
- `reference = circular median(roll[straight])`. If there is less than 10 s of straight riding in total, the median of all samples is used instead.
- `lean = wrap(roll − reference) + offset`, clamped to ±65°.
- **Why:** Riding straight is upright on average. This absorbs the portrait rotation and any skew in the mount.

### Zero-phase smoothing
- Use a centred moving-window filter (`numpy` convolution of a Hann window over the whole series, computed in `prepare`):
  - bike: 0.25 s window
  - helmet: 0.8 s window
- Centred windows over the full series cause no time lag, and the whole series is available offline anyway.
- **Alternative:** Causal exponential smoothing. Rejected because it introduces visible lag.

### State for the running maximum
- `prepare(clip, cfg, (start, end))` computes `lean_s` for the whole clip, then the cumulative max and min arrays from the start index. `draw(t)` indexes into them by nearest sample.

### Drawing
- `base_box` is 380×240 px at 1080 width.
- It draws a rounded semi-transparent black backing (α 0.45), a white arc from −60° to +60° with ticks every 15°, a coloured indicator (accent colour), and the value text with a dark outline.
- The default position is top-left.
- Fonts come from a bundled open-licence font in `app/overlays/assets/`, so the output does not depend on the system's fonts.

## Risks / Trade-offs

- **The DJI fusion may lean toward apparent gravity in long curves** (complementary-filter bias), which would under-read lean.
  → Acceptable for this content. Note it in the README. Compare one long sweeper with the footage during verification.
- **Helmet mode reflects head tilt.**
  → Stronger smoothing reduces glances. The limitation is documented in the setting description shown in the UI.
- **Head turns while riding straight can break the straight-segment detection** (heading rate comes from the camera's yaw).
  → The 3-second minimum and the median make the reference robust to occasional glances.
