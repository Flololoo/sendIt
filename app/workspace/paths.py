"""Locations the workspace reads and writes. Every one can be moved, so tests run in a temporary folder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class WorkspacePaths:
    data_dir: Path
    exports_dir: Path
    videos_dir: Path  # default folder for "Add from folder"
    project_root: Path = PROJECT_ROOT  # relative folder paths from the API resolve against this

    @classmethod
    def default(cls) -> WorkspacePaths:
        return cls(
            data_dir=PROJECT_ROOT / "data",
            exports_dir=PROJECT_ROOT / "exports",
            videos_dir=PROJECT_ROOT / "videos",
        )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.db"

    @property
    def media_dir(self) -> Path:
        """Stored copies of uploaded files."""
        return self.data_dir / "media"

    @property
    def cache_dir(self) -> Path:
        """Telemetry cache root, the same folder the engine uses by default."""
        return self.data_dir / "cache"

    @property
    def clip_cache_dir(self) -> Path:
        """Per-clip thumbnails and generated proxies, in one folder per clip id."""
        return self.cache_dir / "clips"

    @property
    def jobs_path(self) -> Path:
        return self.data_dir / "jobs.json"
