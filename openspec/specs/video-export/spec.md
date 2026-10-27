# video-export Specification

## Purpose

Produces MP4 files with the enabled overlays burned in, ready to post on Instagram Reels and TikTok. Exports run as tracked, cancellable background jobs.

## Requirements

### Requirement: Burned-in export
The system SHALL render a clip with the enabled overlays burned in, to a new MP4 in the exports folder. The output SHALL be in the clip's display orientation, at the source frame rate, with the source audio. The source file SHALL never be modified.

#### Scenario: Export a portrait clip
- **WHEN** clip 0051 is exported with the lean-angle overlay enabled at original resolution
- **THEN** an MP4 of 2160×3840 at 59.94 fps with stereo audio is created, with the overlay visible
- **AND** the source file's size and modification time are unchanged

### Requirement: Export range
An export SHALL accept an optional start time and end time. When they are given, only that range is rendered. Values derived from telemetry for each timestamp, such as the current lean angle, SHALL be identical to those in a full-clip export. Statistics that an overlay declares as range-based, such as a running maximum, SHALL start at the range start.

#### Scenario: Short reel from a long clip
- **WHEN** clip 0051 is exported with start 300 s and end 330 s
- **THEN** the output is 30 s (±1 frame) long and starts with the source frame at 300 s

#### Scenario: Instantaneous value unaffected by range
- **WHEN** the same timestamp is rendered in a full-clip export and in a 300–330 s export
- **THEN** the overlay's instantaneous value at that timestamp is identical in both

#### Scenario: Range-based statistic restarts
- **WHEN** an overlay shows a running maximum and the export starts at 300 s
- **THEN** the maximum shown at 300 s reflects only data from 300 s onwards

#### Scenario: Invalid range
- **WHEN** the start time is not before the end time, or the range lies outside the clip
- **THEN** the export is rejected before rendering starts, with an explanatory message

### Requirement: Output resolution presets
An export SHALL offer the preset "original" (the display resolution of the source) and the preset "social" (1080×1920 for portrait sources, 1920×1080 for landscape).

#### Scenario: Social preset
- **WHEN** a portrait 2160×3840 clip is exported with the social preset
- **THEN** the output is 1080×1920

### Requirement: Platform-compatible encoding
Exported files SHALL use 8-bit H.264 or HEVC video with AAC audio, in MP4 with the moov atom placed at the start (faststart), so that Instagram and TikTok accept them.

#### Scenario: Output codec check
- **WHEN** an export finishes
- **THEN** the output's video is 8-bit H.264 or HEVC, its audio is AAC, and the file is marked faststart

### Requirement: Export job tracking
Each export SHALL run as a background job with a unique id. Its state SHALL be one of queued, running, completed, failed or cancelled. It SHALL report progress as a percentage with an estimated time remaining, and the output path once it has completed. Only one export SHALL run at a time; further exports SHALL be queued.

#### Scenario: Progress reporting
- **WHEN** an export is running
- **THEN** its state reports running, and its progress percentage increases over time until it reaches 100% on completion

#### Scenario: Two exports requested
- **WHEN** a second export is requested while one is running
- **THEN** the second job is queued, and it starts after the first one finishes

### Requirement: Export cancellation
A queued or running export SHALL be cancellable. Cancelling SHALL stop the rendering and delete the partial output.

#### Scenario: Cancel a running export
- **WHEN** a running export is cancelled
- **THEN** its state becomes cancelled, the encoder process stops, and no partial file remains in the exports folder

### Requirement: Export failure reporting
When an export fails, its job SHALL become failed with a human-readable reason. A missing ffmpeg, a full disk and an unreadable source SHALL each produce a reason that names the cause. Partial output SHALL be deleted.

#### Scenario: Disk full
- **WHEN** the encoder fails because no disk space is left
- **THEN** the job is failed, the reason mentions insufficient disk space, and no partial file remains

### Requirement: Export naming
Exported files SHALL be named after the source clip, the enabled overlay ids and the range, plus a numeric suffix if needed. An existing export SHALL never be overwritten.

#### Scenario: Repeated export
- **WHEN** the same clip, range and overlays are exported twice
- **THEN** two distinct files exist, and the second has a numeric suffix
