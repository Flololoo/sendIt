# video-library Specification

## Purpose

Lets the user bring their ride footage into the local app, by uploading it or by referencing files already on disk. Keeps a library of clips with the metadata needed to choose one and work on it.

## Requirements

### Requirement: Local-only access
The app SHALL be served on the loopback interface (127.0.0.1) only, and SHALL NOT be reachable from other machines on the network by default.

#### Scenario: Default start
- **WHEN** the app is started without options
- **THEN** it listens on 127.0.0.1, and the startup output shows the URL to open

### Requirement: Clip upload
The app SHALL accept video uploads by drag-and-drop and through a file picker. Uploads SHALL be streamed to the workspace media folder without holding the whole file in memory. Progress SHALL be shown for each file, and files larger than 10 GB SHALL be supported.

#### Scenario: Upload a 13 GB clip
- **WHEN** the user drops `DJI_20261026164225_0053_D.MP4` (13 GB) onto the library
- **THEN** a per-file progress bar is shown, and the clip appears in the library when the upload completes
- **AND** the app's memory use does not grow with the file size

#### Scenario: Upload interrupted
- **WHEN** an upload is aborted or the connection drops
- **THEN** the partial file is deleted, and the clip does not appear in the library

#### Scenario: Unsupported file
- **WHEN** the user uploads a file that ffprobe cannot read as video
- **THEN** the upload is rejected with a message naming the file, and nothing is added to the library

### Requirement: Import from local folder
The app SHALL let the user add clips from a local folder path, by reference and without copying them. By default the folder is the project's `videos/` folder.

#### Scenario: Add existing footage
- **WHEN** the user imports the folder `videos/`
- **THEN** the three MP4 clips are added to the library, referencing their original paths, with no copies made

#### Scenario: Referenced file goes missing
- **WHEN** a referenced source file is moved or deleted after it was imported
- **THEN** the clip is shown as missing in the library, and preview and export are disabled for it

### Requirement: Proxy pairing
When importing a clip, the app SHALL pair it with a DJI low-resolution proxy (`.LRF`) of the same base name if one exists, whether it is uploaded together with the clip or located next to it. LRF files SHALL NOT appear as clips of their own.

#### Scenario: MP4 and LRF imported together
- **WHEN** `DJI_20261026155823_0051_D.MP4` and `DJI_20261026155823_0051_D.LRF` are imported together
- **THEN** one clip appears in the library, marked as having a proxy

### Requirement: Browser-playable preview source
Every clip SHALL have a browser-playable preview source. The app SHALL use the paired LRF proxy when there is one. Otherwise it SHALL generate an H.264 720p proxy in the background and show its progress.

#### Scenario: Clip without LRF
- **WHEN** a clip without an LRF is imported
- **THEN** a proxy is generated in the background, and the clip becomes playable when proxy generation finishes

### Requirement: Clip listing
The library SHALL list each clip with:
- its embedded cover thumbnail
- file name, duration, recording date and time, and camera model
- telemetry availability, and whether it is missing

Telemetry SHALL be extracted in the background on import.

#### Scenario: Library after importing DJI clips
- **WHEN** the three DJI clips have been imported
- **THEN** each shows a thumbnail, its duration (12:36, 13:14, 15:52), "DJI OsmoAction4" and telemetry available

### Requirement: Duplicate detection
The app SHALL detect when a clip whose file name and size match an existing library entry is imported again. It SHALL reuse the existing entry instead of creating a duplicate.

#### Scenario: Same clip imported twice
- **WHEN** the same MP4 is uploaded a second time
- **THEN** the library still contains one entry for it, and the user is told it already exists

### Requirement: Clip removal
The user SHALL be able to remove a clip from the library:
- Removing an uploaded clip SHALL delete its stored copy and its cache.
- Removing a referenced clip SHALL delete only its library entry and cache, never the original file.
- Exports SHALL be kept.

#### Scenario: Remove a referenced clip
- **WHEN** the user removes a clip that was imported from `videos/`
- **THEN** it disappears from the library, and the original file in `videos/` still exists
