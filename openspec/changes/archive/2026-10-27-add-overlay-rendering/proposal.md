# Proposal

## Why

Each telemetry overlay (lean angle, g-meter, and later ones) has to be drawn frame-accurately and burned into a portrait 4K clip that is ready to post. Positioning, Reels and TikTok safe zones, previews and the encoding pipeline are the same for every overlay. Building them once, as a shared engine with a pluggable overlay contract, means each new overlay only needs its drawing and data logic.

## What Changes

- Define an overlay contract. Each overlay declares:
  - an id, a display name and a description
  - its configurable settings
  - its default position and size
  - whether it requires telemetry
  
  Each overlay draws itself for a given timestamp.
- Add an overlay registry, so new overlays become available without changes to the engine or the UI.
- Add a layout system with position presets and size presets (S/M/L). Default layouts keep overlays inside the Instagram Reels and TikTok safe area.
- Add a preview renderer that returns a single composited frame (video frame plus enabled overlays) for any timestamp.
- Add a burned-in export as a background job:
  - renders the enabled overlays onto the original footage, in portrait orientation, with audio kept
  - offers an optional in/out range
  - offers output resolution presets (original 2160×3840, or 1080×1920 for social)
  - reports progress and supports cancellation
- Exposed as a Python API plus a CLI. The web UI comes in `add-video-workspace`.

## Capabilities

### New Capabilities
- `overlay-composition`: The overlay contract and registry, layout and safe zones, and single-frame preview of overlays on video.
- `video-export`: Burned-in rendering of enabled overlays into an output MP4, as a tracked, cancellable job.

### Modified Capabilities
<!-- none -->

## Impact

- New modules `app/overlays/` (contract, registry) and `app/render/` (preview, export jobs).
- New dependency: Pillow, for drawing overlays.
- Uses ffmpeg for decoding, compositing and encoding. It prefers NVENC on the user's NVIDIA GPU and falls back to software encoding.
- Depends on `add-telemetry-extraction`. The changes that depend on it are `add-video-workspace`, `add-lean-angle-overlay` and `add-g-meter-overlay`.
