# overlay-controls Specification

## Purpose

Gives the user one screen per clip to switch overlays on and off, adjust them, see how they look on the footage, pick the part of the clip to use, and export it.

## Requirements

### Requirement: Overlay toggles
The clip screen SHALL list every registered overlay with an on/off toggle, its name and its description. Overlays that are unavailable for the clip SHALL be shown disabled, with the reason.

#### Scenario: Toggle an overlay on
- **WHEN** the user switches the lean-angle overlay on
- **THEN** its settings become visible, and the preview shows the overlay

#### Scenario: Clip without telemetry
- **WHEN** a clip without telemetry is opened
- **THEN** the telemetry-based overlays are shown disabled, with "no telemetry in this clip"

### Requirement: Camera mount selection
The clip screen SHALL let the user set the camera mount for the clip, either helmet or bike. The mount SHALL be saved with the clip's configuration and passed to every overlay. A clip that has never been configured SHALL start with the most recently used mount.

#### Scenario: Switch mount
- **WHEN** the user switches the mount from bike to helmet while paused
- **THEN** the preview re-renders the overlays using the helmet mount within 1 second

### Requirement: Generated settings controls
For each enabled overlay, the screen SHALL show controls generated from the overlay's declared settings. Enumerations SHALL appear as a select or segmented control, booleans as a switch, and numbers as a slider with their bounds. Each overlay SHALL also have position and size preset controls.

#### Scenario: New overlay added later
- **WHEN** a new overlay with its own settings is registered
- **THEN** it appears on the clip screen with working controls, without any change to the frontend code

### Requirement: Configuration persistence
The overlay configuration (toggles, settings, position, size), the camera mount and the in and out points SHALL be saved per clip. They SHALL be restored when the clip is reopened, including after an app restart. A new clip SHALL start with the most recently used configuration as its default.

#### Scenario: Reopen after restart
- **WHEN** the user configures overlays on a clip, restarts the app and opens the clip again
- **THEN** the same toggles, settings, presets and range are shown

#### Scenario: Next clip of the same ride
- **WHEN** the user opens a clip that has never been configured
- **THEN** it starts with the configuration last saved on any clip

### Requirement: Preview player
The clip screen SHALL play the clip's preview source. When playback is paused or the user scrubs, it SHALL show the composited preview frame for the current position within 1 second. While the video is playing, it SHALL refresh the overlay preview at least twice per second.

#### Scenario: Scrub to a curve
- **WHEN** the user pauses at 304 s in clip 0051 with the lean-angle overlay on
- **THEN** within 1 second the player shows the frame at 304 s with the lean-angle overlay drawn for 304 s

#### Scenario: Settings change while paused
- **WHEN** the user changes an overlay setting while paused
- **THEN** the preview updates to reflect the new setting within 1 second

### Requirement: Safe-area guide toggle
The preview SHALL offer a toggle that shows the social safe-area guides. Guides SHALL never appear in exports.

#### Scenario: Guides on
- **WHEN** the user enables safe-area guides
- **THEN** the guides are drawn on the preview only

### Requirement: Range selection
The user SHALL be able to set in and out points from the current playback position, clear them, and see the selected range and its duration. Without a range, the whole clip SHALL be exported.

#### Scenario: Mark a 30-second reel
- **WHEN** the user sets in at 300 s and out at 330 s
- **THEN** the range 5:00–5:30 (0:30) is shown, and the next export covers only that range

### Requirement: Export from the UI
The clip screen SHALL start an export with the current configuration, range and a chosen resolution preset (original or social). It SHALL show every export job with its state, progress and estimated time remaining, and the job list SHALL update without a page reload. Jobs SHALL be cancellable from the list, and completed exports SHALL be playable and downloadable from it.

#### Scenario: Export and download
- **WHEN** the user exports the marked range at the social preset and the job completes
- **THEN** the job shows completed with a link to play or download the MP4

#### Scenario: Cancel from the UI
- **WHEN** the user cancels a running export
- **THEN** the job shows cancelled, and no file is listed for it

#### Scenario: Export with no overlays enabled
- **WHEN** the user starts an export with every overlay switched off
- **THEN** the app asks for confirmation before exporting the plain clip
