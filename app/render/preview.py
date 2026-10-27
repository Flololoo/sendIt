"""Preview: one composited frame of a clip, with the same overlay layer that export draws."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from app.overlays.config import validate_config
from app.overlays.contract import ClipContext, Mount
from app.overlays.layer import plan_layer, render_layer, union_box
from app.overlays.layout import safe_area
from app.overlays.registry import OverlayRegistry, default_registry
from app.telemetry.cache import DEFAULT_CACHE_ROOT
from app.telemetry.ffmpeg_io import ToolError, require_ffmpeg

from .clip import load_clip, preview_source
from .export import resolve_range

PREVIEW_WIDTH = 720
GUIDE_COLOR = (255, 0, 255, 255)


def grab_frame(source: Path, t: float, width: int = PREVIEW_WIDTH) -> Image.Image:
    """Return the frame at `t` seconds of `source`, auto-rotated to display orientation and `width` px wide."""
    require_ffmpeg()
    cmd = [
        "ffmpeg", "-v", "error", "-ss", f"{t:.6f}", "-i", str(source),
        "-map", "0:v:0", "-frames:v", "1", "-vf", f"scale={width}:-2",
        "-f", "image2pipe", "-c:v", "png", "-",
    ]
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout:
        reason = result.stderr.decode(errors="replace").strip() or "no frame at this time"
        raise ToolError(f"could not read a frame at {t:.3f} s from {source.name}: {reason}")
    return Image.open(BytesIO(result.stdout)).convert("RGB")


def draw_safe_guides(img: Image.Image) -> None:
    """Draw the social safe-area boundary onto a preview image, in place. Never used by export."""
    area = safe_area(img.width, img.height)
    ImageDraw.Draw(img).rectangle(
        [round(area.x0), round(area.y0), round(area.x1) - 1, round(area.y1) - 1],
        outline=GUIDE_COLOR,
        width=max(2, img.width // 360),
    )


def preview(
    clip: str | Path,
    t: float,
    cfg: Mapping[str, Any],
    guides: bool = False,
    *,
    width: int = PREVIEW_WIDTH,
    mount: Mount = "bike",
    registry: OverlayRegistry = default_registry,
    start: float | None = None,
    end: float | None = None,
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> Image.Image:
    """Return the frame at `t` with the enabled overlays composited, at `width` px wide.

    `clip` is the MP4. The frame comes from the LRF when one sits next to it. The overlay
    layer is drawn at the clip's display resolution, the same way export draws it, then
    scaled down. `guides` adds the safe-area boundary on top. `start` and `end` give the
    export range the overlays are prepared for (the whole clip by default), so range-based
    statistics match what the export will show.
    """
    ctx: ClipContext = load_clip(clip, mount, cache_root=cache_root)
    configs = validate_config(cfg, registry)
    rng = resolve_range(start, end, ctx.meta.duration_s)
    frame = grab_frame(preview_source(Path(clip)), t, width)

    meta = ctx.meta
    items = plan_layer(configs, ctx, rng, meta.display_width, meta.display_height)
    if items:
        layer = render_layer(items, t)
        scale = frame.width / meta.display_width
        size = (max(1, round(layer.width * scale)), max(1, round(layer.height * scale)))
        small = layer.resize(size, Image.Resampling.LANCZOS)
        ux0, uy0, _, _ = union_box(items)
        frame = frame.convert("RGBA")
        frame.alpha_composite(small, dest=(round(ux0 * scale), round(uy0 * scale)))
    img = frame.convert("RGB")
    if guides:
        draw_safe_guides(img)
    return img
