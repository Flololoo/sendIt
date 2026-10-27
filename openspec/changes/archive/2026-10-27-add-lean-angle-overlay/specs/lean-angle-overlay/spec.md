# Spec Delta

## Purpose

Shows how far the rider leans in curves. The lean angle is derived from the camera's orientation telemetry, calibrated to the camera mount, and drawn as a gauge on the video.

## ADDED Requirements

### Requirement: Lean overlay registration
The system SHALL register an overlay with id `lean` and the name "Lean angle", which requires telemetry. Its settings are:
- `offset`: −15° to +15°, in 0.5° steps, default 0
- `show_max`: boolean, default on

#### Scenario: Overlay listed
- **WHEN** the overlays for a DJI clip with telemetry are listed
- **THEN** "Lean angle" is available with the settings offset and show_max

### Requirement: Signed lean angle
The system SHALL compute the lean angle for any timestamp, in degrees, as the camera's roll about its viewing direction relative to the upright reference. Leaning right SHALL be positive, and leaning left negative.

#### Scenario: Right-hand curve
- **WHEN** the footage at a timestamp shows the rider leaning into a right-hand curve
- **THEN** the computed lean angle is positive

#### Scenario: Left-hand curve
- **WHEN** the footage at a timestamp shows the rider leaning into a left-hand curve
- **THEN** the computed lean angle is negative

### Requirement: Automatic upright calibration
The system SHALL determine the upright reference for each clip automatically. It SHALL use the camera roll during periods of straight riding, so that the camera's mounting angle, including the portrait rotation, does not appear as lean. The manual `offset` SHALL be added to the result.

#### Scenario: Straight road
- **WHEN** the rider rides straight for several seconds in clip 0051
- **THEN** the displayed lean angle stays within ±3° of 0

#### Scenario: Manual correction
- **WHEN** the user sets offset to +2.0°
- **THEN** every displayed lean value is 2.0° higher than with offset 0 (before rounding)

#### Scenario: Too little straight riding
- **WHEN** a clip contains less than 10 s of straight riding in total
- **THEN** the reference falls back to the clip's median roll, and the angle is still computed

### Requirement: Mount-specific smoothing
The displayed lean angle SHALL be smoothed so that vibration and short jerks do not make it jitter. The amount of smoothing SHALL depend on the clip's camera mount: `helmet` SHALL smooth more strongly than the `bike` mount, to reduce short head movements. Smoothing SHALL NOT shift the signal in time.

#### Scenario: Helmet versus bike
- **WHEN** the same clip is rendered with mount helmet and with mount bike
- **THEN** the helmet series has lower frame-to-frame variation than the bike series
- **AND** the peaks of both series are at the same timestamps (within 0.1 s)

### Requirement: Plausibility limit
The displayed lean angle SHALL be limited to ±65°. Larger computed values SHALL be shown as the limit.

#### Scenario: Implausible value
- **WHEN** the computed angle at a timestamp is 80° (for example, the camera was handled off the bike)
- **THEN** the gauge shows 65°

### Requirement: Lean gauge display
The overlay SHALL draw:
- a semicircular gauge with tick marks every 15°, up to 60° on each side
- an indicator at the current angle
- the current value as a whole number of degrees with a side marker ("L 18°", "R 23°", or "0°" when the rounded value is 0)

It SHALL sit on a semi-transparent backing, so that it stays legible over both bright and dark footage.

#### Scenario: Value display
- **WHEN** the current lean angle is −17.6°
- **THEN** the overlay shows "L 18°", and the indicator points 17.6° to the left

### Requirement: Running maximum display
When `show_max` is on, the overlay SHALL show the largest left lean and largest right lean reached so far in the rendered range, as whole degrees. It SHALL also mark them on the gauge. The values SHALL start at 0 at the beginning of the range.

#### Scenario: Maximum builds up
- **WHEN** an export starts at 300 s and the rider leans 21° right at 304 s
- **THEN** from 304 s onwards the overlay shows "max R 21°" until a larger right lean occurs

#### Scenario: Maximum hidden
- **WHEN** `show_max` is off
- **THEN** no maximum values or marks are drawn
