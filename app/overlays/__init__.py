"""Overlay plug-ins: contract, registry, configuration validation, layout and layer rendering."""

from .config import ConfigError, OverlayConfig, validate_config
from .contract import ClipContext, Overlay, Position, Setting, Size
from .registry import Availability, OverlayRegistry, default_registry

from . import lean as _lean  # noqa: F401  registers the lean overlay
from . import gmeter as _gmeter  # noqa: F401  registers the G-meter overlay

__all__ = [
    "Availability",
    "ClipContext",
    "ConfigError",
    "Overlay",
    "OverlayConfig",
    "OverlayRegistry",
    "Position",
    "Setting",
    "Size",
    "default_registry",
    "validate_config",
]
