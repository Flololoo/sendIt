# Tasks

## 1. App shell

- [x] 1.1 Add the `fastapi`, `uvicorn` and `httpx` dependencies (httpx for the test client), and create `app/web/` with an app factory and `python -m app`. The app binds 127.0.0.1:8765 and opens the browser. Verify that `python -m app` prints the URL, that `GET /` serves the static index, and that a test asserts the bind host is 127.0.0.1.
- [x] 1.2 Create the SQLite schema (`clips`, `overlay_configs`) with WAL mode and a migration-on-start. Verify that a test creates a fresh DB in a temporary directory and checks the tables.

## 2. Library backend

- [x] 2.1 Implement `POST /api/import-folder`, with the MP4/MOV scan, LRF pairing by stem, references only and duplicate detection. Verify a test that imports a temporary folder holding fake-named copies of tiny ffmpeg-generated clips, yielding one entry per MP4 with the proxy flagged.
- [ ] 2.2 Implement the streamed `PUT /api/uploads/{filename}`, writing `.part` and renaming, deleting on disconnect, and probing the file with ffprobe. Verify tests: an upload succeeds, an aborted upload leaves no file, and a non-video upload is rejected. Also verify that memory stays flat while uploading a 2 GB generated file (manual check, with the observation noted in the PR).
- [x] 2.3 Implement the background jobs on import: telemetry extraction, cover-thumbnail extraction, and proxy generation when there is no LRF. Verify tests show the statuses move from pending through running to done, and that a clip without an LRF gets a playable proxy.
- [x] 2.4 Implement `GET /api/clips` (with missing-file detection) and `DELETE /api/clips/{id}`, which deletes upload copies but never referenced originals. Verify tests for both removal kinds.
- [x] 2.5 Serve the proxy and the thumbnail with HTTP Range support. Verify that a test sends a `Range: bytes=0-99` request and gets 206 with 100 bytes.

## 3. Overlay configuration backend

- [x] 3.1 Implement `GET /api/overlays?clip=` (registry plus availability) and `GET/PUT /api/clips/{id}/config` (including the mount; validated through the engine, persisted, and defaulting to the last-used configuration and mount). Verify tests for an invalid setting (422 naming the field), and for persistence across an app restart.
- [x] 3.2 Implement `GET /api/clips/{id}/overlay.png?t&w&guides`, which returns the transparent overlay layer. Verify that a test with the test-only overlay returns a PNG with alpha at the requested width.

## 4. Export backend

- [x] 4.1 Implement `POST /api/clips/{id}/export {preset}` using the saved configuration and range, `GET /api/jobs` and `POST /api/jobs/{id}/cancel`, and serve the export files with Range support and a download disposition. Verify tests that run a 2-second export through the API to completion, and a cancel.

## 5. Frontend

- [ ] 5.1 Build the library view: drag-and-drop zone, file picker, per-file progress, "Add from folder" (prefilled with `videos/`), and cards with thumbnail, duration, time, camera, telemetry status, missing badge and remove. Verify manually by dropping a small clip, importing `videos/`, and seeing three cards with durations 12:36, 13:14 and 15:52.
- [ ] 5.2 Build the clip view: video player on the proxy, the overlay `<img>` layer with the pause, seek and play refresh logic, and the safe-area guide toggle. Verify manually that 0051 plays upright in portrait, and that pausing at 304 s shows the overlay layer within 1 s.
- [ ] 5.3 Build the overlay panel generated from the registry: a mount selector (helmet/bike) at the top, toggles, controls for enum, bool and number settings, position and size presets, disabled state with the reason, and debounced autosave. Verify manually that toggling the test overlay updates the preview, and that the configuration survives a reload.
- [ ] 5.4 Build the range controls (set in, set out, clear, duration display) and the export panel (preset select, confirmation when no overlays are enabled, a live job list with progress, ETA and cancel, and play or download links). Verify manually by exporting 0051 from 300 to 330 s at the social preset and playing the result in the browser.

## 6. Integration check

- [x] 6.1 Run an end-to-end smoke test: start the app, import `videos/`, configure the test overlay, export a 10-second range, and confirm with ffprobe that the output is 1080×1920 at 59.94 fps with H.264 or HEVC and AAC. Document the user workflow in `README.md`.
