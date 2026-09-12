"""The migration runner must be idempotent and must produce the v0.1 schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from meetinglens.db import connect, migrate, open_migrated

EXPECTED_TABLES = {"meeting", "speaker", "utterance", "keyframe", "job", "schema_migration"}


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {str(row["name"]) for row in rows}


def test_migrate_creates_the_schema(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    applied = migrate(conn)
    assert applied == sorted(applied), "migrations must apply in filename order"
    assert applied[0] == "0001_init.sql"
    assert _tables(conn) >= EXPECTED_TABLES
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(keyframe)")}
    assert {"ocr_text", "text_coverage", "dropped", "drop_reason"} <= columns


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    assert migrate(conn) == [], "a second run must apply nothing"


def test_open_migrated_creates_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deeper" / "t.db"
    conn = open_migrated(target)
    assert target.exists()
    conn.close()


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    conn = open_migrated(tmp_path / "t.db")
    try:
        conn.execute(
            "INSERT INTO utterance (meeting_id, start_ms, end_ms, text, source)"
            " VALUES (999, 0, 1, 'orphan', 'vtt')"
        )
    except sqlite3.IntegrityError:
        return
    raise AssertionError("an utterance with no meeting must be rejected")


def test_cascade_delete_removes_children(tmp_path: Path) -> None:
    conn = open_migrated(tmp_path / "t.db")
    conn.execute("INSERT INTO meeting (id, title, source_path) VALUES (1, 'm', '/tmp/a.mp4')")
    conn.execute(
        "INSERT INTO utterance (meeting_id, start_ms, end_ms, text, source)"
        " VALUES (1, 0, 1000, 'hello', 'vtt')"
    )
    conn.commit()
    conn.execute("DELETE FROM meeting WHERE id = 1")
    conn.commit()
    assert conn.execute("SELECT count(*) AS n FROM utterance").fetchone()["n"] == 0
