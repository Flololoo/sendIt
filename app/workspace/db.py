"""SQLite storage: one connection per thread, WAL journal, schema migrations keyed on PRAGMA user_version."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Each migration is a tuple of statements. Position n holds the migration that moves the schema to version n + 1.
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        """
        CREATE TABLE clips (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            origin TEXT NOT NULL CHECK (origin IN ('upload', 'reference')),
            source_path TEXT NOT NULL,
            proxy_path TEXT,
            size INTEGER NOT NULL,
            mtime REAL,
            meta_json TEXT NOT NULL,
            telemetry_status TEXT NOT NULL DEFAULT 'pending',
            thumbnail_status TEXT NOT NULL DEFAULT 'pending',
            proxy_status TEXT NOT NULL DEFAULT 'pending',
            proxy_progress REAL NOT NULL DEFAULT 0,
            error TEXT,
            added_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX clips_name_size ON clips (name, size)",
        """
        CREATE TABLE overlay_configs (
            clip_id TEXT PRIMARY KEY REFERENCES clips (id) ON DELETE CASCADE,
            mount TEXT NOT NULL,
            config_json TEXT NOT NULL,
            range_start REAL,
            range_end REAL,
            updated_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX overlay_configs_updated ON overlay_configs (updated_at)",
    ),
)


class Database:
    """Opens the library database and hands each thread its own connection."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self._migrate()

    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # Autocommit mode; multi-statement writes use transaction(). check_same_thread is off
            # so that close() can reach every connection.
            conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn = conn
            with self._lock:
                self._connections.append(conn)
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")

    def schema_version(self) -> int:
        return int(self.connection().execute("PRAGMA user_version").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            for conn in self._connections:
                conn.close()
            self._connections.clear()
        self._local = threading.local()

    def _migrate(self) -> None:
        conn = self.connection()
        conn.execute("PRAGMA journal_mode = WAL")  # persistent; must run outside a transaction
        with self.transaction() as tx:
            # Read the version inside the write lock, so two processes starting together cannot both migrate.
            version = int(tx.execute("PRAGMA user_version").fetchone()[0])
            if version > len(MIGRATIONS):
                raise RuntimeError(f"{self.path} has schema version {version}, newer than this app understands")
            for number in range(version + 1, len(MIGRATIONS) + 1):
                for statement in MIGRATIONS[number - 1]:
                    tx.execute(statement)
                tx.execute(f"PRAGMA user_version = {number}")
