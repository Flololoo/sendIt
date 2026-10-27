# Spec Delta

## Purpose

Reads the per-frame telemetry and the recording metadata that DJI Osmo Action cameras embed in their video files. Serves this data aligned to the video timeline, for overlays and analysis.

## ADDED Requirements

### Requirement: Telemetry track detection
The system SHALL detect whether a video file contains a DJI meta telemetry track. It SHALL report files without one as having no telemetry, without failing.

#### Scenario: DJI clip with telemetry
- **WHEN** an Osmo Action 4 MP4 such as `DJI_20261026155823_0051_D.MP4` is analyzed
- **THEN** the system reports that telemetry is available

#### Scenario: Video without telemetry
- **WHEN** a video file without a DJI meta track is analyzed
- **THEN** the system reports telemetry as unavailable and returns no samples, without raising an error

### Requirement: Motion sample decoding
The system SHALL decode one sample per telemetry record. Each sample SHALL contain the camera orientation as a unit quaternion and the 3-axis acceleration in units of g.

#### Scenario: Camera at rest
- **WHEN** samples are decoded from a segment where the camera is stationary
- **THEN** the magnitude of each acceleration vector is approximately 1 g (within ±0.1 g)
- **AND** each orientation quaternion has a norm of approximately 1 (within ±0.01)

#### Scenario: Full clip decoded
- **WHEN** a clip with N telemetry records is decoded
- **THEN** exactly N samples are produced

### Requirement: Exposure sample decoding
Each sample SHALL include the exposure values the camera recorded for that frame: ISO, shutter speed (as exposure time in seconds) and white-balance colour temperature in Kelvin.

#### Scenario: Exposure values present
- **WHEN** a sample is decoded from an Osmo Action 4 clip
- **THEN** it includes ISO, shutter speed and white balance

### Requirement: Timeline alignment
Each sample SHALL carry a timestamp in seconds, relative to the start of the video's presentation timeline. That timestamp SHALL come from the container's timing for the record, not from the camera's internal frame counter.

#### Scenario: First and last sample
- **WHEN** a 756.4-second clip is decoded
- **THEN** the first sample has timestamp 0.0
- **AND** the last sample's timestamp is within one frame duration of the clip's video stream duration

#### Scenario: Camera frame counter skips values
- **WHEN** the camera's internal frame counter skips values between records
- **THEN** sample timestamps still follow the container timing, and no samples are invented or dropped

### Requirement: Time-based lookup
The system SHALL return an interpolated motion sample for any timestamp within the clip. It SHALL use spherical interpolation for orientation and linear interpolation for acceleration. It SHALL clamp to the nearest sample outside the clip's range.

#### Scenario: Timestamp between two samples
- **WHEN** a sample is requested at a time halfway between two consecutive records
- **THEN** the returned orientation lies between the two neighbouring orientations, and its acceleration is the mean of the two

#### Scenario: Timestamp past the end
- **WHEN** a sample is requested after the last record
- **THEN** the last record's values are returned

### Requirement: Recording metadata
The system SHALL report clip-level metadata:
- camera model, serial number and firmware version
- resolution and frame rate
- display rotation and the resulting orientation (portrait or landscape)
- duration and recording start time in UTC
- whether GPS data is present

#### Scenario: Portrait clip
- **WHEN** an Osmo Action 4 clip stored as 3840×2160 with a −90° display rotation is analyzed
- **THEN** the system reports display dimensions of 2160×3840 and portrait orientation

#### Scenario: No GPS remote used
- **WHEN** a clip whose GPS fields are empty is analyzed
- **THEN** the metadata reports GPS as unavailable

### Requirement: Telemetry caching
The system SHALL cache decoded telemetry for each video. It SHALL reuse the cache while the source file's size and modification time are unchanged, and SHALL re-extract when either changes.

#### Scenario: Second request for the same clip
- **WHEN** telemetry for an unchanged, already-extracted clip is requested again
- **THEN** it is served from the cache without reading the video's telemetry track again

#### Scenario: Source file replaced
- **WHEN** the source file's size or modification time differs from the cached values
- **THEN** telemetry is extracted again and the cache is replaced

### Requirement: Corrupt record tolerance
The system SHALL skip telemetry records that it cannot decode. It SHALL report how many were skipped and SHALL keep decoding the rest of the clip.

#### Scenario: One truncated record
- **WHEN** a single record in the track is truncated or malformed
- **THEN** decoding completes, that record yields no sample, and the result reports one skipped record

### Requirement: CSV export
The system SHALL export a clip's telemetry as a CSV file with one row per sample. The columns SHALL be: timestamp, the quaternion components, the acceleration components, ISO, shutter speed and white balance.

#### Scenario: Export a clip
- **WHEN** CSV export is requested for a clip with N samples
- **THEN** a CSV with a header row and N data rows is written
