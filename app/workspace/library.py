"""Library tables: clips and per-clip overlay configurations. Holds no file or process logic."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.telemetry import Metadata

from .db import Database

# Pending means queued and not started. Running and done are the states the jobs move through.
PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
LRF = "lrf"  # proxy is the DJI LRF that came with the clip

UPDATABLE = {
    "name", "source_path", "proxy_path", "size", "mtime", "meta", "telemetry_status",
    "thumbnail_status", "proxy_status", "proxy_progress", "error",
}
COLUMNS = {"meta": "meta_json"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class Clip:
    id: str
    name: str
    origin: str  # "upload" (stored copy in data/media) or "reference" (original file on disk)
    source_path: str
    proxy_path: str | None
    size: int
    mtime: float | None
    meta: Metadata
    telemetry_status: str
    thumbnail_status: str
    proxy_status: str
    proxy_progress: float
    error: str | None
    added_at: str


@dataclass(frozen=True)
class ConfigRow:
    clip_id: str
    mount: str
    overlays: dict[str, Any]
    range_start: float | None
    range_end: float | None
    updated_at: str


def _clip(row) -> Clip:
    return Clip(
        id=row["id"],
        name=row["name"],
        origin=row["origin"],
        source_path=row["source_path"],
        proxy_path=row["proxy_path"],
        size=row["size"],
        mtime=row["mtime"],
        meta=Metadata.from_dict(json.loads(row["meta_json"])),
        telemetry_status=row["telemetry_status"],
        thumbnail_status=row["thumbnail_status"],
        proxy_status=row["proxy_status"],
        proxy_progress=row["proxy_progress"],
        error=row["error"],
        added_at=row["added_at"],
    )


def _config(row) -> ConfigRow:
    return ConfigRow(
        clip_id=row["clip_id"],
        mount=row["mount"],
        overlays=json.loads(row["config_json"]),
        range_start=row["range_start"],
        range_end=row["range_end"],
        updated_at=row["updated_at"],
    )


class Library:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def _conn(self):
        return self._db.connection()

    # Clips

    def get(self, clip_id: str) -> Clip | None:
        row = self._conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        return _clip(row) if row else None

    def all(self) -> list[Clip]:
        rows = self._conn.execute("SELECT * FROM clips ORDER BY name, added_at").fetchall()
        return [_clip(row) for row in rows]

    def find_by_name_size(self, name: str, size: int) -> Clip | None:
        """The duplicate rule: same file name and same size."""
        row = self._conn.execute(
            "SELECT * FROM clips WHERE name = ? AND size = ? ORDER BY added_at LIMIT 1", (name, size)
        ).fetchone()
        return _clip(row) if row else None

    def named_stem(self, stem: str) -> list[Clip]:
        return [clip for clip in self.all() if Path(clip.name).stem == stem]

    def uses_proxy(self, path: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM clips WHERE proxy_path = ? LIMIT 1", (path,)).fetchone()
        return row is not None

    def insert(
        self,
        *,
        name: str,
        origin: str,
        source_path: str,
        size: int,
        mtime: float | None,
        meta: Metadata,
        proxy_path: str | None = None,
        proxy_status: str = PENDING,
    ) -> Clip:
        clip_id = uuid.uuid4().hex
        self._conn.execute(
            """
            INSERT INTO clips (id, name, origin, source_path, proxy_path, size, mtime, meta_json,
                               proxy_status, proxy_progress, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_id, name, origin, source_path, proxy_path, size, mtime,
                json.dumps(meta.to_dict()), proxy_status, 100.0 if proxy_status == LRF else 0.0, now_iso(),
            ),
        )
        return self.get(clip_id)

    def update(self, clip_id: str, *, only_if: dict[str, str] | None = None, **fields: Any) -> bool:
        """Set columns on one clip. `only_if` makes the update conditional; returns False if nothing matched."""
        unknown = set(fields) - UPDATABLE
        if unknown:
            raise ValueError(f"cannot update clip fields: {sorted(unknown)}")
        if "meta" in fields:
            fields["meta"] = json.dumps(fields["meta"].to_dict())
        columns = {COLUMNS.get(key, key): value for key, value in fields.items()}
        conditions = {"id": clip_id, **(only_if or {})}
        assignments = ", ".join(f"{column} = ?" for column in columns)
        where = " AND ".join(f"{column} = ?" for column in conditions)
        cursor = self._conn.execute(
            f"UPDATE clips SET {assignments} WHERE {where}", (*columns.values(), *conditions.values())
        )
        return cursor.rowcount > 0

    def delete(self, clip_id: str) -> None:
        self._conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))

    # Overlay configurations

    def get_config(self, clip_id: str) -> ConfigRow | None:
        row = self._conn.execute("SELECT * FROM overlay_configs WHERE clip_id = ?", (clip_id,)).fetchone()
        return _config(row) if row else None

    def last_config(self) -> ConfigRow | None:
        """The configuration saved most recently on any clip."""
        row = self._conn.execute("SELECT * FROM overlay_configs ORDER BY updated_at DESC LIMIT 1").fetchone()
        return _config(row) if row else None

    def save_config(
        self,
        clip_id: str,
        *,
        mount: str,
        overlays: dict[str, Any],
        range_start: float | None,
        range_end: float | None,
    ) -> ConfigRow:
        updated_at = now_iso()
        self._conn.execute(
            """
            INSERT INTO overlay_configs (clip_id, mount, config_json, range_start, range_end, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (clip_id) DO UPDATE SET
                mount = excluded.mount, config_json = excluded.config_json,
                range_start = excluded.range_start, range_end = excluded.range_end,
                updated_at = excluded.updated_at
            """,
            (clip_id, mount, json.dumps(overlays), range_start, range_end, updated_at),
        )
        return ConfigRow(clip_id, mount, overlays, range_start, range_end, updated_at)

