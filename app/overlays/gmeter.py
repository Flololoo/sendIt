"""G-meter and bump overlay: a circular g-meter with a trail, bump call-outs and a bump counter.

The meter shows the horizontal g-forces (braking at the bottom, accelerating at the top, right
positive). Bumps come from the vertical acceleration. Both are computed in `gmeter_signal`.
When the meter is hidden the box keeps its base size (the overlay contract has no per-config
box), and only the call-out and counter are drawn, in the top region.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import hypot
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .contract import ClipContext, Setting
from .gmeter_signal import bump_candidates, decompose_samples, filter_bumps, meter_components
from .lean import FONT_PATH
from .registry import default_registry

BOX = (300, 360)
TOP_REGION_H = 96  # the part used when the meter is hidden
SUPERSAMPLE = 3
BACKING = (0, 0, 0, 115)  # alpha 0.45, as the lean overlay
WHITE = (255, 255, 255, 255)
OUTLINE = (0, 0, 0, 255)
ACCENT = (255, 150, 0, 255)
TRAIL = (110, 200, 255)
GREY = (255, 255, 255, 110)

CENTRE = (150, 190)
FULL_SCALE_G = 1.2
RING_G = (0.5, 1.0)
RADIUS = 96  # the 1.2 g edge, in base pixels
TRAIL_S = 1.0
TRAIL_POINTS = 15
CALLOUT_HOLD_S = 1.0
CALLOUT_FADE_S = 0.5
CALLOUT_BADGE = (150, 34)  # centre of the call-out badge
COUNTER_Y = 80  # when the meter is hidden; with the meter the counter sits below the value
VALUE_Y = 312
COUNTER_Y_METER = 345
SENSITIVITIES = ("low", "medium", "high")


@dataclass(frozen=True)
class GMeterState:
    """Per-clip series for `draw`. Counts start at zero at the start of the rendered range."""

    t: np.ndarray
    longitudinal: np.ndarray  # smoothed, g
    lateral: np.ndarray  # smoothed, g
    event_t: np.ndarray  # all bump events, sorted
    event_peak: np.ndarray
    count: np.ndarray  # cumulative events from the range start, aligned with `t`
    show_meter: bool
    show_bumps: bool
    show_count: bool


def _empty_state(cfg: dict[str, Any]) -> GMeterState:
    empty = np.zeros(0)
    return GMeterState(
        empty, empty, empty, empty, empty, np.zeros(0, dtype=int),
        cfg["show_meter"], cfg["show_bumps"], cfg["show_bump_count"],
    )


def _index(t_series: np.ndarray, t: float) -> int:
    """Index of the last sample at or before `t`, clamped to the series."""
    return int(np.clip(np.searchsorted(t_series, t, side="right") - 1, 0, len(t_series) - 1))


def total_g(state: GMeterState, t: float) -> float:
    """Total horizontal g at time `t`, by linear interpolation of the smoothed components."""
    if len(state.t) == 0:
        return 0.0
    lon = float(np.interp(t, state.t, state.longitudinal))
    lat = float(np.interp(t, state.t, state.lateral))
    return hypot(lon, lat)


def value_text(g: float) -> str:
    return f"{g:.1f} g"


def callout_at(state: GMeterState, t: float) -> tuple[str, float] | None:
    """(text, alpha) of the call-out showing at `t`, or None. The newest event replaces older ones."""
    if len(state.event_t) == 0:
        return None
    i = int(np.searchsorted(state.event_t, t, side="right")) - 1
    if i < 0:
        return None
    age = t - float(state.event_t[i])
    if age >= CALLOUT_HOLD_S + CALLOUT_FADE_S:
        return None
    alpha = 1.0 if age <= CALLOUT_HOLD_S else 1.0 - (age - CALLOUT_HOLD_S) / CALLOUT_FADE_S
    return f"BUMP {float(state.event_peak[i]):.1f} g", alpha


def count_text(n: int) -> str:
    return f"Bumps: {n}"


def bump_count(state: GMeterState, t: float) -> int:
    if len(state.t) == 0:
        return 0
    return int(state.count[_index(state.t, t)])


def labels(state: GMeterState, t: float) -> list[str]:
    """The texts `draw` writes at time `t`: the value, the call-out, the counter, when shown."""
    out: list[str] = []
    if state.show_meter:
        out.append(value_text(total_g(state, t)))
    if state.show_bumps:
        shown = callout_at(state, t)
        if shown is not None:
            out.append(shown[0])
        if state.show_count:
            out.append(count_text(bump_count(state, t)))
    return out


def ring_radius(g: float) -> float:
    """Radius of the ring for `g`, in base pixels."""
    return g * RADIUS / FULL_SCALE_G


def dot_position(state: GMeterState, t: float) -> tuple[float, float]:
    """Centre of the dot at time `t`, in base pixels, clamped to the 1.2 g edge."""
    if len(state.t) == 0:
        return float(CENTRE[0]), float(CENTRE[1])
    lon = float(np.interp(t, state.t, state.longitudinal))
    lat = float(np.interp(t, state.t, state.lateral))
    return _to_screen(lat, lon, RADIUS / FULL_SCALE_G)


def trail_times(t: float) -> np.ndarray:
    """The last TRAIL_S seconds, as TRAIL_POINTS times from oldest to newest."""
    return t - np.linspace(TRAIL_S, 0.0, TRAIL_POINTS)


@lru_cache(maxsize=None)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


def _to_screen(lat: float, lon: float, scale: float) -> tuple[float, float]:
    """Screen point in base pixels for (lateral right, longitudinal forward), clamped to the 1.2 g edge."""
    m = hypot(lat, lon)
    if m > FULL_SCALE_G:
        lat, lon = lat * FULL_SCALE_G / m, lon * FULL_SCALE_G / m
    return CENTRE[0] + lat * scale, CENTRE[1] - lon * scale


def _text(d: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, size: float, anchor: str,
          fill: tuple[int, int, int, int] = WHITE) -> None:
    size = round(size)
    d.text(xy, text, font=_font(size), fill=fill, anchor=anchor,
           stroke_width=max(2, size // 14), stroke_fill=OUTLINE)


class GMeterOverlay:
    id = "gmeter"
    name = "G-meter & bumps"
    description = (
        "Horizontal g-forces from the camera's accelerometer and orientation, with bump call-outs. "
        "On a helmet, the travel direction follows the bike slowly, so head turns do not rotate the meter."
    )
    requires_telemetry = True
    settings = [
        Setting(key="show_meter", type="bool", default=True, label="Show G-meter"),
        Setting(key="show_bumps", type="bool", default=True, label="Show bump call-outs"),
        Setting(key="show_bump_count", type="bool", default=True, label="Show bump counter"),
        Setting(key="sensitivity", type="enum", default="medium", label="Bump sensitivity",
                choices=SENSITIVITIES),
    ]
    default_position = "middle-right"
    default_size = "M"
    base_box = BOX

    def validate(self, cfg: dict[str, Any]) -> list[str]:
        if not cfg["show_meter"] and not cfg["show_bumps"]:
            return ["at least one part must be shown: enable show_meter or show_bumps"]
        return []

    def prepare(self, clip: ClipContext, cfg: dict[str, Any], rng: tuple[float, float]) -> GMeterState:
        tel = clip.telemetry
        if tel is None or len(tel) < 2:
            return _empty_state(cfg)
        d = decompose_samples(tel.samples, clip.mount)
        lon, lat = meter_components(d)
        events = filter_bumps(bump_candidates(d.t, d.vertical), cfg["sensitivity"])
        ev_t = np.array([e.t for e in events], dtype=float)
        ev_p = np.array([e.peak_g for e in events], dtype=float)
        in_range = ev_t[ev_t >= rng[0]]
        count = np.searchsorted(in_range, d.t, side="right").astype(int)
        return GMeterState(
            d.t, lon, lat, ev_t, ev_p, count,
            bool(cfg["show_meter"]), bool(cfg["show_bumps"]), bool(cfg["show_bump_count"]),
        )

    def draw(self, img: Image.Image, t: float, state: GMeterState) -> None:
        callout = callout_at(state, t) if state.show_bumps else None
        counter = state.show_bumps and state.show_count
        if not state.show_meter and callout is None and not counter:
            return

        k = SUPERSAMPLE * img.width / BOX[0]
        big = Image.new("RGBA", (round(BOX[0] * k), round(BOX[1] * k)), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        if state.show_meter:
            d.rounded_rectangle((0, 0, big.width - 1, big.height - 1), radius=24 * k, fill=BACKING)
            self._meter(d, t, state, k)
        else:
            d.rounded_rectangle((0, 0, big.width - 1, round(TOP_REGION_H * k) - 1), radius=24 * k, fill=BACKING)

        if callout is not None:
            self._callout(d, callout, k)
        if counter:
            self._counter(d, bump_count(state, t), k, COUNTER_Y_METER if state.show_meter else COUNTER_Y)

        small = big.resize(img.size, Image.LANCZOS)
        img.alpha_composite(small)

    def _meter(self, d: ImageDraw.ImageDraw, t: float, state: GMeterState, k: float) -> None:
        cx, cy = CENTRE[0] * k, CENTRE[1] * k
        scale = RADIUS / FULL_SCALE_G

        for g in RING_G:
            r = g * scale * k
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=GREY, width=round(3 * k))
        r_edge = RADIUS * k
        d.ellipse((cx - r_edge, cy - r_edge, cx + r_edge, cy + r_edge), outline=WHITE, width=round(4 * k))
        d.line([(cx - r_edge, cy), (cx + r_edge, cy)], fill=GREY, width=round(2 * k))
        d.line([(cx, cy - r_edge), (cx, cy + r_edge)], fill=GREY, width=round(2 * k))
        for g in RING_G:
            _text(d, (cx + g * scale * k * 0.707 + 4 * k, cy - g * scale * k * 0.707 - 4 * k),
                  f"{g:.1f}", 15 * k, "lb", fill=GREY)

        if len(state.t):
            times = trail_times(t)
            lon = np.interp(times, state.t, state.longitudinal)
            lat = np.interp(times, state.t, state.lateral)
            pts = [_to_screen(float(a), float(b), scale) for a, b in zip(lat, lon)]
            for i in range(1, len(pts)):
                alpha = round(255 * (i / (len(pts) - 1)) ** 2 * 0.8)
                d.line([(pts[i - 1][0] * k, pts[i - 1][1] * k), (pts[i][0] * k, pts[i][1] * k)],
                       fill=(*TRAIL, alpha), width=round(6 * k))
            x, y = dot_position(state, t)
            r = 9 * k
            d.ellipse((x * k - r, y * k - r, x * k + r, y * k + r), fill=ACCENT, outline=WHITE, width=round(2 * k))

        _text(d, (cx, VALUE_Y * k), value_text(total_g(state, t)), 40 * k, "mm")

    @staticmethod
    def _callout(d: ImageDraw.ImageDraw, callout: tuple[str, float], k: float) -> None:
        text, alpha = callout
        a = round(255 * alpha)
        font = _font(round(26 * k))
        left, top, right, bottom = font.getbbox(text, anchor="mm")
        half_w = (right - left) / 2 + 14 * k
        cx, cy = CALLOUT_BADGE[0] * k, CALLOUT_BADGE[1] * k
        h = 22 * k
        d.rounded_rectangle((cx - half_w, cy - h, cx + half_w, cy + h), radius=h, fill=(*ACCENT[:3], a))
        d.text((cx, cy), text, font=font, fill=(*OUTLINE[:3], a), anchor="mm")

    @staticmethod
    def _counter(d: ImageDraw.ImageDraw, n: int, k: float, y: float) -> None:
        text = count_text(n)
        font = _font(round(24 * k))
        width = font.getlength(text)
        cx, cy = CENTRE[0] * k, y * k
        icon_r = 14 * k
        ix = cx - width / 2 - icon_r - 8 * k
        # A small road-bump icon: a flat line with a rounded hump.
        base = cy + 6 * k
        d.line([(ix - icon_r, base), (ix + icon_r, base)], fill=WHITE, width=round(3 * k))
        d.arc((ix - icon_r * 0.7, base - icon_r * 0.9, ix + icon_r * 0.7, base + icon_r * 0.5),
              180, 360, fill=WHITE, width=round(3 * k))
        d.text((cx, cy), text, font=font, fill=WHITE, anchor="mm", stroke_width=max(2, round(24 * k) // 14),
               stroke_fill=OUTLINE)


GMETER = GMeterOverlay()
if default_registry.get(GMETER.id) is None:
    default_registry.register(GMETER)
