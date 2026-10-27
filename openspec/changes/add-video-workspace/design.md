# Design

## Context

This change adds the user interface on top of two engine changes:
- `add-telemetry-extraction`, which provides `get_telemetry` and metadata.
- `add-overlay-rendering`, which provides the overlay registry, configuration validation, `preview`, the overlay layer renderer and `ExportQueue`.

It is a single user on one Windows machine, and the footage is in the 10 to 13 GB range. LRF proxies are H.264 1280×720, which Chrome and Edge play. HEVC 10-bit masters generally do not play in Chrome or Edge on Windows without extensions.

## Goals / Non-Goals

**Goals:**
- Zero-build frontend, started with one command.
- The UI is generated from the overlay registry, so new overlays need no frontend work.
- Never block the UI on heavy work. Extraction, proxy generation and export all run in the background.

**Non-Goals:**
- Multiple users, authentication, remote access.
- Mobile layout. This is a desktop browser tool.
- A timeline editor or multi-clip sequences.

## Decisions

### Backend: FastAPI + uvicorn on 127.0.0.1:8765
- The app starts with `python -m app`, which also opens the default browser.
- **Why:** It is the same language as the engine, its async endpoints are a good fit for streamed uploads, and static files are built in.
- **Alternative:** Flask. Its streaming uploads and range responses need more hand-rolled code.

### Frontend: static HTML + vanilla ES modules
- Files live in `app/web/static/`. There is no bundler and no npm.
- **Why:** There are about three screens (library, clip, jobs), so a framework's build chain costs more than it gives.
- **Alternative:** React + Vite. Revisit it if the UI grows.

### Storage: SQLite (stdlib `sqlite3`) in `data/library.db`
- Tables:
  - `clips`: id, display name, source_path, origin = upload|reference, proxy_path, size, mtime, meta_json, telemetry_status, proxy_status
  - `overlay_configs`: clip_id, mount, config_json, range_start, range_end, updated_at
- The "last used config" is the row with the most recent `updated_at` (requirement: Configuration persistence).

### Uploads
- The browser sends each file through `XMLHttpRequest` (for `upload.onprogress`) as a raw `PUT /api/uploads/{filename}`, with the body streamed.
- The server iterates over `request.stream()` into `data/media/<name>.part`, then renames the file on completion and deletes it on disconnect.
- **Why:** Multipart parsing of a 13 GB body is wasteful. A raw PUT streams with constant memory.
- Uploads in one drop are processed MP4s-first, so the LRFs can pair to them. An LRF that arrives without a matching MP4 is held for 60 s and then discarded.

### Folder import by reference
- `POST /api/import-folder {path}` scans for `*.MP4`/`*.MOV` and pairs `*.LRF` by stem.
- Referenced files are never written to. A cheap `os.stat` on list and open detects missing files.

### Background work
- A small `ThreadPoolExecutor` (2 workers) for telemetry extraction, cover-thumbnail extraction (`-map 0:v:1 -frames:v 1`, the MJPEG cover stream) and proxy generation (`libx264 720p`, when there is no LRF).
- Exports use the single-worker `ExportQueue` from `add-overlay-rendering`.

### Preview mechanics
- The `<video>` element plays the proxy through a `FileResponse` with HTTP Range support, so seeking works.
- A transparent `<img>` layer on top shows `GET /api/clips/{id}/overlay.png?t=…&w=720&guides=…`. This is the overlay layer only, rendered by the same code as export, at the preview width.
- The layer is requested on `pause`, `seeked` and setting changes (debounced 150 ms), and every 400 ms while playing. A request that is in flight is skipped, which avoids a backlog.
- **Why:** Server-rendered overlays keep a single drawing implementation (requirement: Deterministic overlay drawing). Sending only the overlay layer keeps the video smooth.
- **Alternative:** Reimplementing the overlays on a JS canvas. That gives a smoother live preview but two implementations that would drift apart.

### Live updates
- The jobs list and the background statuses are polled with `GET /api/jobs` and `GET /api/clips` every 1 s while something is active.
- **Why:** Simpler than SSE or WebSockets, and the load is negligible on localhost.

### Exports in the UI
- Completed files are served from `exports/` with Range support, for in-browser playback and as a download (`Content-Disposition`).

## Risks / Trade-offs

- **Proxy orientation.** The LRF is stored landscape and may rely on a rotation flag.
  → Chrome and Edge honour MP4 display matrices. If a proxy plays sideways, apply a CSS rotation based on the clip metadata. A task verifies this on clip 0051.
- **Copying 10+ GB uploads doubles disk use.**
  → The UI recommends "Add from folder" for files already on this machine. Uploading stays available for files coming from SD cards or other locations.
- **Preview refresh at 400 ms is not frame-perfect while playing.**
  → It is acceptable for a quick check. The paused preview is exact.
- **Threads plus SQLite.**
  → One connection per thread, with WAL mode enabled.
