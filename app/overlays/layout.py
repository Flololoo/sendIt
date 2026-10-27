"""Layout: turns position and size presets into boxes inside the social safe area.

All geometry is in frame pixels. Sizes scale with the frame width, so the same
preset covers the same fraction of the frame at every output resolution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, floor

from .contract import POSITIONS, SIZES, Position, Size

REFERENCE_WIDTH = 1080
SIZE_SCALE: dict[str, float] = {"S": 0.75, "M": 1.0, "L": 1.35}

# Safe-area insets: top and bottom are fractions of the frame height, left and right of its width.
SAFE_TOP = 0.12
SAFE_BOTTOM = 0.25
SAFE_LEFT = 0.04
SAFE_RIGHT = 0.15

# Gap between stacked overlays, as a fraction of the frame height.
STACK_GAP = 0.02


@dataclass(frozen=True)
class Box:
    """Rectangle in frame pixels: (x0, y0) top-left, (x1, y1) bottom-right, exclusive."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def intersects(self, other: Box) -> bool:
        return self.x0 < other.x1 and other.x0 < self.x1 and self.y0 < other.y1 and other.y0 < self.y1

    def contains(self, other: Box, eps: float = 1e-6) -> bool:
        return (
            other.x0 >= self.x0 - eps
            and other.y0 >= self.y0 - eps
            and other.x1 <= self.x1 + eps
            and other.y1 <= self.y1 + eps
        )

    def to_pixels(self) -> tuple[int, int, int, int]:
        """Integer box rounded inwards, so it never extends past this box."""
        return (ceil(self.x0), ceil(self.y0), floor(self.x1), floor(self.y1))


@dataclass(frozen=True)
class Placement:
    """One overlay to place: `key` identifies it in the result (the overlay id)."""

    key: str
    position: Position
    size: Size
    base_box: tuple[int, int]


def safe_area(frame_w: float, frame_h: float) -> Box:
    return Box(
        SAFE_LEFT * frame_w,
        SAFE_TOP * frame_h,
        (1 - SAFE_RIGHT) * frame_w,
        (1 - SAFE_BOTTOM) * frame_h,
    )


def scaled_size(base_box: tuple[int, int], size: Size, frame_w: float) -> tuple[float, float]:
    """Return (width, height) of a box for `size` on a frame `frame_w` pixels wide."""
    if size not in SIZE_SCALE:
        raise ValueError(f"unknown size {size!r}, expected one of {list(SIZES)}")
    k = SIZE_SCALE[size] * frame_w / REFERENCE_WIDTH
    return base_box[0] * k, base_box[1] * k


def place_overlays(placements: Sequence[Placement], frame_w: int, frame_h: int) -> dict[str, Box]:
    """Return the box of every placement, keyed by `key`.

    Overlays that share a position are stacked from the edge (top or bottom) or
    centred as a group (middle), in the order given, with a STACK_GAP between them.
    Raises ValueError if a box or a stack does not fit inside the safe area.
    """
    area = safe_area(frame_w, frame_h)
    gap = STACK_GAP * frame_h

    groups: dict[str, list[Placement]] = {}
    for p in placements:
        if p.position not in POSITIONS:
            raise ValueError(f"{p.key}: unknown position {p.position!r}")
        groups.setdefault(p.position, []).append(p)

    boxes: dict[str, Box] = {}
    for position, group in groups.items():
        sizes = [scaled_size(p.base_box, p.size, frame_w) for p in group]
        for p, (w, _) in zip(group, sizes):
            if w > area.width:
                raise ValueError(f"{p.key}: width {w:.0f}px does not fit the safe area")
        total = sum(h for _, h in sizes) + gap * (len(group) - 1)
        if total > area.height:
            raise ValueError(f"{position}: stacked height {total:.0f}px does not fit the safe area")

        vertical, horizontal = position.split("-")
        if vertical == "bottom":
            # The first overlay in registry order sits on the bottom edge, the next above it.
            y = area.y1
            for p, (w, h) in zip(group, sizes):
                boxes[p.key] = _box_at(horizontal, area, w, y - h, h)
                y -= h + gap
        else:
            y = area.y0 if vertical == "top" else (area.y0 + area.y1 - total) / 2
            for p, (w, h) in zip(group, sizes):
                boxes[p.key] = _box_at(horizontal, area, w, y, h)
                y += h + gap

    return {p.key: boxes[p.key] for p in placements}


def preset_box(
    position: Position, size: Size, base_box: tuple[int, int], frame_w: int, frame_h: int
) -> Box:
    """Return the box for one overlay placed alone at a preset."""
    return place_overlays([Placement("overlay", position, size, base_box)], frame_w, frame_h)["overlay"]


def _box_at(horizontal: str, area: Box, w: float, y0: float, h: float) -> Box:
    if horizontal == "left":
        x0 = area.x0
    elif horizontal == "right":
        x0 = area.x1 - w
    else:
        x0 = (area.x0 + area.x1 - w) / 2
    return Box(x0, y0, x0 + w, y0 + h)
