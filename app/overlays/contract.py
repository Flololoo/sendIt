"""Overlay contract: settings, placement presets, the clip context and the Overlay protocol."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, get_args

from PIL import Image

from app.telemetry import Metadata, Telemetry

Position = Literal[
    "top-left",
    "top-center",
    "top-right",
    "middle-left",
    "middle-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
]
POSITIONS: tuple[str, ...] = get_args(Position)

Size = Literal["S", "M", "L"]
SIZES: tuple[str, ...] = get_args(Size)

Mount = Literal["helmet", "bike"]
SettingType = Literal["enum", "int", "float", "bool"]


@dataclass(frozen=True)
class Setting:
    """One configurable overlay setting.

    `choices` applies to enum settings, `min` and `max` to int and float settings.
    """

    key: str
    type: SettingType
    default: Any
    label: str
    choices: tuple[Any, ...] | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None  # granularity hint for the number input of an int or float setting


@dataclass(frozen=True)
class ClipContext:
    """What an overlay knows about the clip it is drawn on."""

    path: Path
    meta: Metadata
    telemetry: Telemetry | None
    mount: Mount = "bike"


class Overlay(Protocol):
    """Contract every overlay implements.

    `base_box` is the (width, height) in pixels at the 1080-px-wide reference frame, size M.
    `prepare` runs once per preview or export and returns the state for `draw`.
    `draw` receives an RGBA image the size of the overlay's own box, transparent at the
    start, with (0, 0) at its top-left corner, and must be pure for each `t`.
    An overlay may also define `validate(cfg: dict) -> list[str]` for rules that span
    several settings. It is optional and is called with the filled-in settings.
    """

    id: str
    name: str
    description: str
    requires_telemetry: bool
    settings: list[Setting]
    default_position: Position
    default_size: Size
    base_box: tuple[int, int]

    def prepare(self, clip: ClipContext, cfg: dict[str, Any], rng: tuple[float, float]) -> Any:
        """Precompute per-clip series. `rng` is the (start, end) range in seconds."""
        ...

    def draw(self, img: Image.Image, t: float, state: Any) -> None:
        """Draw the overlay at time `t` into its own box-sized image."""
        ...
