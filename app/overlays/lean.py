"""Lean angle overlay: a semicircular gauge with the current lean, and the running maximum on each side."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import cos, floor, radians, sin
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .contract import ClipContext, Setting
from .lean_signal import lean_series
from .registry import default_registry

FONT_PATH = Path(__file__).parent / "assets" / "Barlow-SemiBold.ttf"

BOX = (380, 240)
SUPERSAMPLE = 3
BACKING = (0, 0, 0, 115)  # alpha 0.45
WHITE = (255, 255, 255, 255)
OUTLINE = (0, 0, 0, 255)
ACCENT = (255, 150, 0, 255)
MAX_MARK = (110, 200, 255, 255)

CENTRE = (190, 170)
RADIUS = 140
SCALE_DEG = 60
TICK_STEP_DEG = 15
OFFSET_STEP = 0.5


@dataclass(frozen=True)
class LeanState:
    """Per-clip series for `draw`. The maxima are zero before the start of the rendered range."""

    t: np.ndarray
    lean: np.ndarray
    max_left: np.ndarray
    max_right: np.ndarray
    show_max: bool


def _rounded(angle: float) -> int:
    return floor(abs(angle) + 0.5)


def value_text(angle: float) -> str:
    n = _rounded(angle)
    if n == 0:
        return "0°"
    return f"{'L' if angle < 0 else 'R'} {n}°"


def max_texts(max_left: float, max_right: float) -> tuple[str, str]:
    return f"max L {_rounded(max_left)}°", f"max R {_rounded(max_right)}°"


def sample_at(state: LeanState, t: float) -> tuple[float, float, float]:
    """Return (lean, max left, max right) at time `t`, by nearest sample."""
    n = len(state.t)
    if n == 0:
        return 0.0, 0.0, 0.0
    lean = float(np.interp(t, state.t, state.lean))
    i = int(np.clip(round(float(np.interp(t, state.t, np.arange(n)))), 0, n - 1))
    return lean, float(state.max_left[i]), float(state.max_right[i])


def labels(state: LeanState, t: float) -> list[str]:
    """The texts `draw` writes at time `t`: the value, then the two maxima when they are shown."""
    lean, left, right = sample_at(state, t)
    out = [value_text(lean)]
    if state.show_max:
        out.extend(max_texts(left, right))
    return out


@lru_cache(maxsize=None)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


def _polar(angle_deg: float, radius: float, k: float) -> tuple[float, float]:
    """Point at `angle_deg` from straight up (right positive) and `radius`, in supersampled pixels."""
    a = radians(angle_deg)
    return (CENTRE[0] + radius * sin(a)) * k, (CENTRE[1] - radius * cos(a)) * k


class LeanOverlay:
    id = "lean"
    name = "Lean angle"
    description = (
        "Lean angle from the camera's orientation. In helmet mode it follows head tilt, "
        "so it usually reads lower than the bike's lean."
    )
    requires_telemetry = True
    settings = [
        Setting(key="offset", type="float", default=0.0, label="Offset (°)", min=-15.0, max=15.0, step=OFFSET_STEP),
        Setting(key="show_max", type="bool", default=True, label="Show maximum"),
    ]
    default_position = "top-left"
    default_size = "M"
    base_box = BOX

    def validate(self, cfg: dict[str, Any]) -> list[str]:
        if (cfg["offset"] / OFFSET_STEP) % 1 != 0:
            return [f"offset must be a multiple of {OFFSET_STEP}"]
        return []

    def prepare(self, clip: ClipContext, cfg: dict[str, Any], rng: tuple[float, float]) -> LeanState:
        tel = clip.telemetry
        if tel is None or len(tel) < 2:
            empty = np.zeros(0)
            return LeanState(empty, empty, empty, empty, cfg["show_max"])
        t, lean = lean_series(tel, clip.mount, float(cfg["offset"]))
        start = int(np.searchsorted(t, rng[0], side="left"))
        right = np.zeros(len(t))
        left = np.zeros(len(t))
        if start < len(t):
            right[start:] = np.maximum.accumulate(np.maximum(lean[start:], 0.0))
            left[start:] = np.maximum.accumulate(np.maximum(-lean[start:], 0.0))
        return LeanState(t, lean, left, right, cfg["show_max"])

    def draw(self, img: Image.Image, t: float, state: LeanState) -> None:
        lean, max_left, max_right = sample_at(state, t)
        k = SUPERSAMPLE * img.width / BOX[0]
        big = Image.new("RGBA", (round(BOX[0] * k), round(BOX[1] * k)), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)

        d.rounded_rectangle((0, 0, big.width - 1, big.height - 1), radius=24 * k, fill=BACKING)

        cx, cy = CENTRE[0] * k, CENTRE[1] * k
        r = RADIUS * k
        d.arc((cx - r, cy - r, cx + r, cy + r), -90 - SCALE_DEG, -90 + SCALE_DEG, fill=WHITE, width=round(6 * k))
        for deg in range(-SCALE_DEG, SCALE_DEG + 1, TICK_STEP_DEG):
            major = deg % 30 == 0
            d.line(
                [_polar(deg, RADIUS, k), _polar(deg, RADIUS - (22 if major else 12), k)],
                fill=WHITE, width=round(4 * k),
            )

        if state.show_max:
            for deg in (-max_left, max_right):
                if abs(deg) >= 0.5:
                    d.line(
                        [_polar(deg, RADIUS + 4, k), _polar(deg, RADIUS + 20, k)],
                        fill=MAX_MARK, width=round(5 * k),
                    )

        angle = float(np.clip(lean, -65.0, 65.0))
        d.polygon(
            [_polar(angle, RADIUS - 4, k), _polar(angle - 5, RADIUS - 36, k), _polar(angle + 5, RADIUS - 36, k)],
            fill=ACCENT,
        )

        texts = labels(state, t)
        self._text(d, (CENTRE[0] * k, 150 * k), texts[0], 70 * k, "mm")
        if state.show_max:
            self._text(d, (22 * k, 216 * k), texts[1], 28 * k, "lm")
            self._text(d, ((BOX[0] - 22) * k, 216 * k), texts[2], 28 * k, "rm")

        small = big.resize(img.size, Image.LANCZOS)
        img.alpha_composite(small)

    @staticmethod
    def _text(d: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, size: float, anchor: str) -> None:
        size = round(size)
        d.text(xy, text, font=_font(size), fill=WHITE, anchor=anchor, stroke_width=max(2, size // 14), stroke_fill=OUTLINE)


LEAN = LeanOverlay()
if default_registry.get(LEAN.id) is None:
    default_registry.register(LEAN)
