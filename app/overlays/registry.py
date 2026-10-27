"""Overlay registry: the available overlays and which of them a clip can use."""

from __future__ import annotations

from dataclasses import dataclass

from .contract import ClipContext, Overlay

NO_TELEMETRY = "no telemetry"


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str | None = None


class OverlayRegistry:
    """Holds overlays keyed by id, in registration order."""

    def __init__(self) -> None:
        self._overlays: dict[str, Overlay] = {}

    def register(self, overlay: Overlay) -> Overlay:
        if overlay.id in self._overlays:
            raise ValueError(f"overlay id already registered: {overlay.id!r}")
        self._overlays[overlay.id] = overlay
        return overlay

    def get(self, overlay_id: str) -> Overlay | None:
        return self._overlays.get(overlay_id)

    def overlays(self) -> list[Overlay]:
        return list(self._overlays.values())

    def index(self, overlay_id: str) -> int | None:
        """Return the registration index of `overlay_id`, or None if it is not registered."""
        return list(self._overlays).index(overlay_id) if overlay_id in self._overlays else None

    def availability(self, overlay: Overlay, clip: ClipContext) -> Availability:
        if overlay.requires_telemetry and clip.telemetry is None:
            return Availability(False, NO_TELEMETRY)
        return Availability(True)

    def overlays_for(self, clip: ClipContext) -> list[tuple[Overlay, Availability]]:
        return [(o, self.availability(o, clip)) for o in self._overlays.values()]


default_registry = OverlayRegistry()
