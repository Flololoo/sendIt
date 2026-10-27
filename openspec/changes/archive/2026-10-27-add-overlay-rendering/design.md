# Design

## Context

The source clips are 4K HEVC 10-bit at 59.94 fps, about 110 Mbit/s, stored as 3840×2160 with a −90° display matrix. ffmpeg auto-rotates them on decode, so the clips are 2160×3840 portrait as displayed.

The machine runs Windows 11 with an NVIDIA GPU (the NVIDIA app and PhysX are installed). It has ffmpeg 8.1 in the full build, which includes `hevc_nvenc`, `h264_nvenc`, `libx264` and `libx265`.

Telemetry comes from `add-telemetry-extraction` through `get_telemetry(path)` and `Telemetry.at(t)`.

## Goals / Non-Goals

**Goals:**
- One drawing code path for preview and export (requirement: Deterministic overlay drawing).
- Overlays as plug-ins, defined by a small Python contract.
- Exporting a 30 to 90 second reel should take minutes, not hours, on this machine.

**Non-Goals:**
- Overlay-only (transparent) export. It is not wanted now. The two-pass design below keeps it cheap to add later.
- Trimming, cutting and multi-clip editing, beyond a single in/out range.
- Free drag-and-drop positioning. Presets only for now.

## Decisions

### The overlay contract
```python
class Overlay(Protocol):
    id: str; name: str; description: str
    requires_telemetry: bool
    settings: list[Setting]            # Setting(key, type: enum|int|float|bool, choices/min/max, default, label)
    default_position: Position; default_size: Size
    base_box: tuple[int, int]          # box in px at the reference 1080-wide frame, size M
    def validate(self, cfg: dict) -> list[str]: ...   # optional cross-setting rules; returns error messages (default: none)
    def prepare(self, clip: ClipContext, cfg: dict, rng: tuple[float, float]) -> Any: ...   # precompute series
    def draw(self, img: PIL.Image.Image, t: float, state: Any) -> None: ...                  # draw into its box
```
- `ClipContext` has the fields `path`, `meta`, `telemetry | None` and `mount: Literal["helmet", "bike"]`. The mount is a property of the clip, not an overlay setting, because several overlays (lean, g-meter) depend on it.
- `prepare` runs once per preview session or export. It computes derived series, such as filtered lean, over the whole clip, so values do not depend on the range (requirement: Export range).
- `draw` is pure for each value of `t`.
- A registry module holds the overlays, and the overlay modules register themselves on import.

### Layout engine
- The reference frame is 1080 px wide. S, M and L scale `base_box` by 0.75, 1.0 and 1.35, and the result is then scaled to the output width.
- The safe-area insets are percentages, which makes them resolution-independent.
- When several overlays share a preset, they are stacked inwards from the edge with a 2% gap, in registry order.

### Export pipeline: two passes
- **Pass 1, per export:** Python draws each frame of the overlay layer (RGBA, cropped to the union bounding box of all enabled overlays, not the full frame). The frames are piped as `rawvideo rgba` to an ffmpeg process that encodes them losslessly to a temporary `qtrle` or `ffv1` `.mov` with alpha.
- **Pass 2:** ffmpeg decodes the source (with `-hwaccel cuda` if available), auto-rotates it, scales it to the chosen preset, and composites it with `overlay=x:y`. It encodes with `hevc_nvenc -preset p5 -cq 20`, falling back to `libx264 -crf 18`, uses `-pix_fmt yuv420p`, copies or re-encodes the audio as AAC, and sets `-movflags +faststart`.
- **Why:**
  - Piping the full 2160×3840 RGBA frame would mean 33 MB per frame, or about 2 GB/s at 60 fps. A cropped overlay box is about 1 to 2 MB.
  - Windows named pipes for a second live ffmpeg input are fragile, and the temporary file avoids them.
  - The temporary alpha file is also exactly what a future overlay-only export would produce.
- **Alternatives:**
  - A single pass with Python compositing every frame. Far too slow.
  - The ffmpeg `drawtext`/`ass` filters. They cannot draw gauges.
  - Rendering in the browser (canvas) and capturing. Not deterministic, and it duplicates the drawing code.

### Overlay frame rate equals output frame rate
- 59.94 fps. Drawing a small gauge with Pillow takes about 1 to 3 ms, so a 90-second reel (5,400 frames) needs about 15 s for pass 1. Full-clip exports scale linearly, and that is acceptable.

### Preview
- `preview(clip, t, cfg, guides)` grabs one frame with `ffmpeg -ss t -i <LRF if present, else MP4> -frames:v 1`, using the LRF for speed, and scales it to the preview width (720 px).
- It then composites the same overlay layer that export uses, scaled down. Because pixel identity applies at equal resolution (see the spec), the test compares overlay layers, not full frames.

### Jobs
- An in-process `ExportQueue`: one worker thread, a FIFO, and job records kept in memory and mirrored to `data/jobs.json`.
- Progress is parsed from ffmpeg's `-progress pipe:1` (`out_time_ms`). Pass 1 counts as 15% of the progress and pass 2 as 85%.
- Cancelling terminates the ffmpeg processes and deletes the temporary and partial files.

### Output naming
- Files go to `exports/<clip-stem>__<overlay-ids>__<start>-<end>.mp4`, with `_2`, `_3` and so on when a name already exists.

### CLI
- `python -m app.render export <clip> --overlay lean --overlay gmeter --start 300 --end 330 --preset social` drives the same queue synchronously, so it can be tested before the UI exists.

## Risks / Trade-offs

- **NVENC is missing or fails** (driver, session limit).
  → Probe `hevc_nvenc` once at startup with a 1-frame null encode, and fall back to `libx264` automatically. Log which encoder was used.
- **10-bit decode plus CUDA hwaccel plus the CPU overlay filter needs frame downloads.**
  → Use `-hwaccel cuda` without `-hwaccel_output_format cuda` so frames land in system memory. Accept the throughput, and benchmark it in tasks.
- **Seek accuracy for ranges.** HEVC is long-GOP.
  → Use output-side accurate seeking (`-ss` before `-i` plus `-accurate_seek`, which ffmpeg does by default when transcoding). The overlay uses source timestamps offset by the range start.
- **Temporary alpha files can be large for full-clip exports.**
  → Crop to the union box. Delete the file after pass 2 or on cancel.
