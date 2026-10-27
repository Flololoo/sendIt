"""Test-only overlay and clip helpers for the overlay tests."""

from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.overlays.contract import ClipContext, Setting
from app.telemetry import Metadata, Samples, Telemetry


@lru_cache(maxsize=None)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


class TimestampOverlay:
    """Draws the frame time as text, large and outlined so it reads on video. Settings: decimals (0-4) and unit (s or ms)."""

    id = "timestamp"
    name = "Timestamp"
    description = "Test overlay that prints the frame time."
    requires_telemetry = False
    settings = [
        Setting(key="decimals", type="int", default=2, label="Decimals", min=0, max=4),
        Setting(key="unit", type="enum", default="s", label="Unit", choices=("s", "ms")),
    ]
    default_position = "top-left"
    default_size = "M"
    base_box = (400, 120)

    def prepare(self, clip: ClipContext, cfg: dict[str, Any], rng: tuple[float, float]) -> Any:
        return dict(cfg)

    def draw(self, img: Image.Image, t: float, state: Any) -> None:
        value = t * 1000 if state["unit"] == "ms" else t
        text = f"{value:.{state['decimals']}f}{state['unit']}"
        size = max(12, round(img.height * 0.7))
        ImageDraw.Draw(img).text(
            (0, 0), text, font=_font(size), fill=(255, 255, 255, 255),
            stroke_width=max(2, size // 14), stroke_fill=(0, 0, 0, 255),
        )

    def validate(self, cfg: dict[str, Any]) -> list[str]:
        if cfg["unit"] == "ms" and cfg["decimals"] > 0:
            return ["unit 'ms' requires decimals 0"]
        return []


class RangeRecordingOverlay(TimestampOverlay):
    """Draws nothing. Records every range it is prepared for, so tests can check the range used."""

    id = "range_recording"
    name = "Range recording"
    description = "Test overlay that records the range passed to prepare."

    def __init__(self) -> None:
        self.prepared: list[tuple[float, float]] = []

    def prepare(self, clip: ClipContext, cfg: dict[str, Any], rng: tuple[float, float]) -> Any:
        self.prepared.append(rng)
        return dict(cfg)

    def draw(self, img: Image.Image, t: float, state: Any) -> None:
        pass


class TelemetryOverlay(TimestampOverlay):
    """Same drawing as TimestampOverlay, but needs telemetry."""

    id = "telemetry_stub"
    name = "Telemetry stub"
    description = "Test overlay that needs telemetry."
    requires_telemetry = True


def make_clip(with_telemetry: bool, mount: str = "bike") -> ClipContext:
    meta = Metadata(
        source="DJI_TEST_0051_D.MP4",
        telemetry_available=with_telemetry,
        proto_schema=None,
        model=None,
        serial=None,
        firmware=None,
        width=3840,
        height=2160,
        fps=59.94,
        rotation=-90,
        display_width=2160,
        display_height=3840,
        orientation="portrait",
        duration_s=60.0,
        start_utc=None,
        has_gps=False,
    )
    telemetry = Telemetry(samples=Samples.empty(), meta=meta) if with_telemetry else None
    return ClipContext(path=Path("DJI_TEST_0051_D.MP4"), meta=meta, telemetry=telemetry, mount=mount)
