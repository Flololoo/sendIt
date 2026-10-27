# Spec Delta

## Purpose

Makes the forces of riding visible. Shows braking, acceleration and cornering as a g-meter, and calls out bumps in the road. Both are derived from the camera's accelerometer and orientation telemetry.

## ADDED Requirements

### Requirement: G-meter overlay registration
The system SHALL register an overlay with id `gmeter` and the name "G-meter & bumps", which requires telemetry. Its settings are:
- `show_meter`: boolean, default on
- `show_bumps`: boolean, default on
- `show_bump_count`: boolean, default on
- `sensitivity`: low, medium or high, default medium

#### Scenario: Overlay listed
- **WHEN** the overlays for a DJI clip with telemetry are listed
- **THEN** "G-meter & bumps" is available with these four settings

#### Scenario: Both parts off
- **WHEN** `show_meter` and `show_bumps` are both off
- **THEN** the configuration is rejected, with a message that at least one part must be shown

### Requirement: Gravity-free acceleration
The system SHALL compute, for every timestamp, the acceleration in g with gravity removed, using the camera orientation. It SHALL express it as three components:
- longitudinal (positive = accelerating, negative = braking)
- lateral (positive = to the right)
- vertical

#### Scenario: Standing still
- **WHEN** the camera is at rest
- **THEN** all three components are within ±0.05 g of 0 after smoothing

### Requirement: Direction of travel
Longitudinal and lateral SHALL be relative to the direction of travel. The system SHALL estimate that direction from the camera's horizontal viewing direction, smoothed more strongly for the `helmet` mount than for the `bike` mount, so that brief head turns do not rotate the g-meter.

#### Scenario: Glance over the shoulder on a helmet mount
- **WHEN** with mount helmet, the camera's heading turns 60° for 0.5 s and turns back, while the rider rides straight at a constant speed
- **THEN** the displayed g-meter dot stays within 0.1 g of the centre

### Requirement: Horizontal g display
When `show_meter` is on, the overlay SHALL draw:
- a circular g-meter with rings at 0.5 g and 1.0 g, braking at the bottom and accelerating at the top
- a dot at the current smoothed longitudinal and lateral g, with a trail of the last 1 s
- the current total horizontal g to one decimal place ("0.4 g")

Values beyond 1.2 g SHALL be drawn at the edge.

#### Scenario: Braking
- **WHEN** the smoothed longitudinal acceleration is −0.4 g and the lateral is 0
- **THEN** the dot is drawn below the centre, at 0.4 of the 1.0 g ring radius, and "0.4 g" is shown

#### Scenario: Meter hidden
- **WHEN** `show_meter` is off
- **THEN** no g-meter is drawn

### Requirement: Bump detection
The system SHALL detect bump events as short peaks in vertical acceleration whose magnitude exceeds the threshold for the chosen sensitivity. Events less than 1 s apart SHALL merge into one event, with the highest peak. Each event SHALL have a timestamp and a peak value in g. A higher sensitivity SHALL detect every event that a lower one detects.

#### Scenario: Sensitivity ordering
- **WHEN** bumps are detected on the same clip at low, medium and high sensitivity
- **THEN** the low events are a subset of the medium events, and the medium events are a subset of the high events (matched within 0.1 s)

#### Scenario: Pothole double hit
- **WHEN** front and rear wheel hit the same pothole 0.3 s apart
- **THEN** a single bump event is reported, with the larger of the two peaks

#### Scenario: Smooth road
- **WHEN** a segment has no vertical peaks above the threshold
- **THEN** no bump events are reported for it

### Requirement: Bump call-out
When `show_bumps` is on, the overlay SHALL show a call-out at each bump event, reading "BUMP" and the peak value ("BUMP 1.4 g"). The call-out SHALL appear at the event's timestamp, stay fully visible for 1.0 s and fade out over 0.5 s. A new event SHALL replace a call-out that is still showing.

#### Scenario: Call-out timing
- **WHEN** a bump event occurs at 324.2 s
- **THEN** the call-out is fully visible from 324.2 s to 325.2 s, and has faded out completely by 325.7 s

### Requirement: Bump counter
When `show_bumps` and `show_bump_count` are on, the overlay SHALL show the number of bump events since the start of the rendered range.

#### Scenario: Counter in a range
- **WHEN** an export of 300–330 s contains 3 bump events
- **THEN** the counter shows 0 at 300 s, counts up at each event, and shows 3 at the end
