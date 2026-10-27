"""Request bodies. Values are checked further by the workspace, which knows the registry and the clip."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ImportIn(BaseModel):
    path: str | None = None  # a folder; relative paths resolve against the project root; default videos/


class RangeIn(BaseModel):
    start: float | None = None
    end: float | None = None


class ConfigIn(BaseModel):
    mount: str | None = None  # helmet | bike; default: the clip's current mount
    overlays: dict[str, Any] | None = None  # overlay id -> {enabled, position, size, settings}
    range: RangeIn | None = None  # in and out points in seconds; null means the whole clip


class ExportIn(BaseModel):
    preset: str = "original"  # original | social
