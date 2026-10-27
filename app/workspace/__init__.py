"""Workspace: the local clip library (SQLite), its files, background jobs and the overlay configuration per clip."""

from .errors import BadRequest, Conflict, Invalid, NotFound, Unavailable, Unsupported, WorkspaceError
from .library import Clip, ConfigRow, Library
from .paths import WorkspacePaths
from .service import ConfigView, ExportArgs, ImportResult, UploadResult, UploadTarget, Workspace

__all__ = [
    "BadRequest",
    "Clip",
    "ConfigRow",
    "ConfigView",
    "Conflict",
    "ExportArgs",
    "ImportResult",
    "Invalid",
    "Library",
    "NotFound",
    "UploadResult",
    "UploadTarget",
    "Unavailable",
    "Unsupported",
    "Workspace",
    "WorkspacePaths",
    "WorkspaceError",
]
