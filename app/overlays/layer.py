"""Overlay layer: draws the enabled overlays into one transparent RGBA image.

The image is cropped to the union of the overlays' pixel boxes, not the full frame.
Preview and export both call `render_layer`, so they draw identical pixels.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PIL import Image

from .config import OverlayConfig
from .contract import ClipContext, Overlay
from .layout import Placement, place_overlays

PixelBox = tuple[int, int, int, int]


@dataclass(frozen=True)
class LayerItem:
    """An overlay ready to draw: its pixel box in frame coordinates and its prepared state."""

    overlay: Overlay
    box: PixelBox
    state: Any


def union_box(items: Sequence[LayerItem]) -> PixelBox:
    return (
        min(i.box[0] for i in items),
        min(i.box[1] for i in items),
        max(i.box[2] for i in items),
        max(i.box[3] for i in items),
    )


def render_layer(items: Sequence[LayerItem], t: float) -> Image.Image:
    """Return the overlay layer at time `t` as RGBA, cropped to the union box of `items`.

    Each overlay's `draw` gets its own RGBA image the size of its box, transparent at the
    start, with (0, 0) at the box's top-left. The results are alpha-composited in order.
    """
    if not items:
        return Image.new("RGBA", (0, 0))
    ux0, uy0, ux1, uy1 = union_box(items)
    layer = Image.new("RGBA", (ux1 - ux0, uy1 - uy0), (0, 0, 0, 0))
    for item in items:
        x0, y0, x1, y1 = item.box
        sub = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
        item.overlay.draw(sub, t, item.state)
        layer.alpha_composite(sub, dest=(x0 - ux0, y0 - uy0))
    return layer


def plan_layer(
    configs: Mapping[str, OverlayConfig],
    clip: ClipContext,
    rng: tuple[float, float],
    frame_w: int,
    frame_h: int,
) -> list[LayerItem]:
    """Lay out the enabled overlays and run each one's `prepare`. Registry order is kept."""
    enabled = [c for c in configs.values() if c.enabled]
    placements = [
        Placement(c.overlay.id, c.position, c.size, c.overlay.base_box) for c in enabled
    ]
    boxes = place_overlays(placements, frame_w, frame_h)
    return [
        LayerItem(
            overlay=c.overlay,
            box=boxes[c.overlay.id].to_pixels(),
            state=c.overlay.prepare(clip, c.settings, rng),
        )
        for c in enabled
    ]
