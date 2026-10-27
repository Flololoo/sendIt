# Proposal

## Why

The telemetry and rendering engine is only usable from the command line. The goal is a simple interface: drop in the footage from a ride, switch the overlays you want on or off, check them on a preview, and export a clip ready to post. Each file is 10 to 13 GB, so the app runs locally on the same machine as the footage, not as a hosted service.

## What Changes

- A local web app, served on `localhost`, that opens in the browser.
- **Video library:**
  - Upload clips by drag-and-drop or a file picker. Uploads are streamed to the workspace with progress.
  - Alternatively, add files from a local folder (by default `videos/`) without copying them.
  - DJI `.LRF` proxies with the same name are paired automatically and used for playback.
  - Each clip shows its thumbnail, duration, recording time, camera and telemetry status.
- **Overlay controls per clip:**
  - Toggle each registered overlay on or off.
  - Overlay settings are generated from each overlay's declared settings.
  - Position and size presets.
  - The configuration is saved per clip.
- **Preview:**
  - A video player with the composited overlays shown on pause and while scrubbing.
  - An optional safe-area guide.
  - In and out points set from the current playback position.
- **Export:**
  - Start a burned-in export with a resolution preset.
  - Watch the job progress, cancel it, and open or download the finished file.

## Capabilities

### New Capabilities
- `video-library`: Importing clips (upload or local folder), pairing proxies, and listing clips with their metadata in the local app.
- `overlay-controls`: The per-clip user interface for toggling and configuring overlays, previewing them, choosing a range and running exports.

### Modified Capabilities
<!-- none -->

## Impact

- New `app/workspace/` (library storage, SQLite) and `app/web/`:
  - FastAPI with an HTTP API
  - a static frontend with no build step
- New dependencies: `fastapi`, `uvicorn`, `python-multipart`.
- New local data folders: `data/media/` (uploads), `data/cache/`, `data/library.db`, `exports/`.
- Depends on `add-telemetry-extraction` and `add-overlay-rendering`. The lean-angle and g-meter overlays appear here automatically once those changes land.
