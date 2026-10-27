"""Overlay configuration: validation against declared settings, with defaults filled in.

A configuration maps overlay ids to entries:
    {"lean": {"enabled": True, "position": "top-left", "size": "M", "settings": {...}}}
Every entry key is optional. A present entry is enabled unless `enabled` is False.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .contract import POSITIONS, SIZES, Overlay, Position, Setting, Size
from .registry import OverlayRegistry, default_registry

FIELDS = ("enabled", "position", "size", "settings")


class ConfigError(ValueError):
    """Raised with every validation error found; each message names the offending field."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class OverlayConfig:
    overlay: Overlay
    enabled: bool
    position: Position
    size: Size
    settings: dict[str, Any]


def validate_config(
    config: Mapping[str, Any], registry: OverlayRegistry = default_registry
) -> dict[str, OverlayConfig]:
    """Validate a configuration and return the resolved entry per overlay id.

    The result is in registry order, whatever order `config` was written in, so layout,
    drawing order and export names do not depend on the caller's dict order.
    Raises ConfigError listing all problems found.
    """
    if not isinstance(config, Mapping):
        raise ConfigError(["config: must be a mapping of overlay id to settings"])

    def registry_rank(item: tuple[Any, Any]) -> int:
        index = registry.index(item[0])
        return len(registry.overlays()) if index is None else index  # unknown ids are reported last

    errors: list[str] = []
    resolved: dict[str, OverlayConfig] = {}
    for oid, entry in sorted(config.items(), key=registry_rank):
        overlay = registry.get(oid)
        if overlay is None:
            errors.append(f"{oid}: unknown overlay")
            continue
        if not isinstance(entry, Mapping):
            errors.append(f"{oid}: must be a mapping of fields")
            continue
        for key in entry:
            if key not in FIELDS:
                errors.append(f"{oid}.{key}: unknown field")

        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            errors.append(f"{oid}.enabled: must be true or false")
        position = entry.get("position", overlay.default_position)
        if position not in POSITIONS:
            errors.append(f"{oid}.position: {position!r} is not one of {list(POSITIONS)}")
        size = entry.get("size", overlay.default_size)
        if size not in SIZES:
            errors.append(f"{oid}.size: {size!r} is not one of {list(SIZES)}")

        given = entry.get("settings", {})
        if isinstance(given, Mapping):
            n_before = len(errors)
            settings = _validate_settings(oid, overlay, given, errors)
            if len(errors) == n_before and hasattr(overlay, "validate"):
                errors.extend(overlay.validate(settings))
        else:
            errors.append(f"{oid}.settings: must be a mapping of setting values")
            settings = {}

        resolved[oid] = OverlayConfig(overlay, enabled, position, size, settings)

    if errors:
        raise ConfigError(errors)
    return resolved


def _validate_settings(
    oid: str, overlay: Overlay, given: Mapping[str, Any], errors: list[str]
) -> dict[str, Any]:
    """Check the given setting values and return them with defaults filled in."""
    declared = {s.key for s in overlay.settings}
    for key in given:
        if key not in declared:
            errors.append(f"{oid}.settings.{key}: unknown setting")

    values: dict[str, Any] = {}
    for setting in overlay.settings:
        if setting.key not in given:
            values[setting.key] = setting.default
            continue
        value = given[setting.key]
        problem = _check_value(setting, value)
        if problem is None:
            values[setting.key] = value
        else:
            errors.append(f"{oid}.settings.{setting.key}: {problem}")
    return values


def _check_value(setting: Setting, value: Any) -> str | None:
    """Return a description of what is wrong with `value`, or None if it is valid."""
    if setting.type == "enum":
        choices = list(setting.choices or ())
        return None if value in choices else f"{value!r} is not one of {choices}"
    if setting.type == "bool":
        return None if isinstance(value, bool) else "must be true or false"
    if setting.type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return "must be an integer"
    elif setting.type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "must be a number"
    else:
        return f"unsupported setting type {setting.type!r}"

    if setting.min is not None and value < setting.min:
        return f"{value} is below the minimum {setting.min}"
    if setting.max is not None and value > setting.max:
        return f"{value} is above the maximum {setting.max}"
    return None
