# overlay-composition Specification

## Purpose

Defines how overlays plug into the system, where they are placed on the frame, and how one composited preview frame of video plus overlays is produced. The same composition is used for previews and for exports.

## Requirements

### Requirement: Overlay registry
The system SHALL keep a registry of available overlays. Each overlay SHALL provide:
- a unique id, a display name and a short description
- a list of configurable settings, each with a type, allowed values and a default
- a flag saying whether it requires telemetry

#### Scenario: Listing overlays
- **WHEN** the list of available overlays is requested
- **THEN** every registered overlay is returned with its id, name, description, settings and telemetry requirement

#### Scenario: Overlay unavailable for a clip
- **WHEN** overlays are listed for a clip without telemetry
- **THEN** overlays that require telemetry are marked unavailable for that clip, with the reason "no telemetry"

### Requirement: Clip context for overlays
When drawing, every overlay SHALL receive the clip context: recording metadata, telemetry (if available), and the clip's camera mount, which is either `helmet` or `bike`. When no mount has been set, it SHALL be `bike`.

#### Scenario: Mount passed to overlays
- **WHEN** a clip configured with mount `helmet` is previewed or exported
- **THEN** every enabled overlay receives mount `helmet` in its clip context

### Requirement: Overlay configuration validation
The system SHALL validate an overlay configuration (enabled flag, position, size and setting values) against the overlay's declared settings. It SHALL reject unknown overlays, unknown settings and out-of-range values, with a message that names the offending field.

#### Scenario: Invalid setting value
- **WHEN** a configuration sets an overlay's enumerated setting to a value that is not among its allowed values
- **THEN** the configuration is rejected and the error names that setting

#### Scenario: Overlay-specific rule violated
- **WHEN** a configuration breaks a rule an overlay declares across several of its settings
- **THEN** the configuration is rejected with that overlay's error message

#### Scenario: Missing settings
- **WHEN** a configuration enables an overlay without specifying its settings
- **THEN** the overlay's default values are used

### Requirement: Position and size presets
Each enabled overlay SHALL be placed by a position preset (top-left, top-center, top-right, middle-left, middle-right, bottom-left, bottom-center, bottom-right) and a size preset (S, M, L). Size SHALL scale with the output frame, so an overlay looks the same at every output resolution.

#### Scenario: Same layout at two resolutions
- **WHEN** the same configuration is composited at 2160×3840 and at 1080×1920
- **THEN** the overlay occupies the same fraction of the frame at the same relative position in both

### Requirement: Social safe area
By default, overlays SHALL be placed inside a safe area that avoids the parts of the frame covered by the Instagram Reels and TikTok interface. The insets are:
- top: 12% of the frame height
- bottom: 25% of the frame height
- right: 15% of the frame width
- left: 4% of the frame width

#### Scenario: Bottom-right preset
- **WHEN** an overlay is placed at bottom-right on a portrait frame
- **THEN** its bounding box lies entirely above the bottom 25% and left of the right 15% of the frame

### Requirement: Overlap resolution
When two enabled overlays share a position preset, the system SHALL stack them along the frame edge in registry order, so that they do not overlap.

#### Scenario: Two overlays at top-left
- **WHEN** two overlays are both set to top-left
- **THEN** their bounding boxes do not intersect

### Requirement: Preview frame
The system SHALL produce a single preview image for a clip at a given timestamp. The image SHALL show the video frame in its display orientation, with all enabled overlays composited exactly as they will appear in the export. It SHALL optionally also show the safe-area guides.

#### Scenario: Preview at a timestamp
- **WHEN** a preview at t = 304.0 s is requested for clip 0051 with one overlay enabled
- **THEN** a portrait image is returned that shows the video frame at 304.0 s with that overlay drawn for 304.0 s

#### Scenario: Safe-area guides
- **WHEN** a preview is requested with guides enabled
- **THEN** the safe-area boundary is drawn on the preview, and it never appears in exports

### Requirement: Deterministic overlay drawing
For a given clip, timestamp and configuration, an overlay SHALL draw identical pixels every time, whether it is drawing a preview or an export frame.

#### Scenario: Preview matches export
- **WHEN** the overlay layer for t = 10.0 s is drawn once for a preview and once during an export at the same resolution
- **THEN** both overlay layers are pixel-identical
