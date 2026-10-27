"""Task 1.2: SQLite schema with WAL mode, migrated on start."""

import sqlite3
import threading

from app.workspace.db import MIGRATIONS, Database


def test_fresh_database_gets_the_schema(tmp_path):
    db = Database(tmp_path / "library.db")
    conn = db.connection()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"clips", "overlay_configs"} <= tables

    clip_columns = {row[1] for row in conn.execute("PRAGMA table_info(clips)")}
    assert {"id", "name", "origin", "source_path", "proxy_path", "size", "mtime", "meta_json",
            "telemetry_status", "proxy_status"} <= clip_columns
    config_columns = {row[1] for row in conn.execute("PRAGMA table_info(overlay_configs)")}
    assert {"clip_id", "mount", "config_json", "range_start", "range_end", "updated_at"} <= config_columns

    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.schema_version() == len(MIGRATIONS)
    db.close()


def test_reopening_keeps_data_and_does_not_migrate_again(tmp_path):
    first = Database(tmp_path / "library.db")
    conn = first.connection()
    conn.execute(
        "INSERT INTO clips (id, name, origin, source_path, size, meta_json, added_at) "
        "VALUES ('c', 'a.MP4', 'reference', '/x/a.MP4', 1, '{}', 'now')"
    )
    conn.execute(
        "INSERT INTO overlay_configs (clip_id, mount, config_json, updated_at) VALUES ('c', 'bike', '{}', 'now')"
    )
    first.close()

    second = Database(tmp_path / "library.db")
    rows = second.connection().execute("SELECT COUNT(*) FROM overlay_configs").fetchone()[0]
    assert rows == 1
    assert second.schema_version() == len(MIGRATIONS)
    second.close()


def test_each_thread_gets_its_own_connection(tmp_path):
    db = Database(tmp_path / "library.db")
    main_conn = db.connection()
    seen = []

    def worker():
        seen.append(db.connection())

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert seen[0] is not main_conn
    assert db.connection() is main_conn
    db.close()


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "library.db"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    conn.close()
    try:
        Database(path)
    except RuntimeError as exc:
        assert "newer" in str(exc)
    else:
        raise AssertionError("expected a RuntimeError for a newer schema")
