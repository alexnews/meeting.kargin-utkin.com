"""SQLite connection and the forward-only migration runner.

Migrations ship inside the package so an installed tool can create its own
database with no repository checkout.
"""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

MIGRATIONS_PACKAGE = "meetinglens.migrations"


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the database, creating its directory if needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _migration_files() -> list[tuple[str, str]]:
    """Every packaged migration, sorted by filename so order is the numbering."""
    found: list[tuple[str, str]] = []
    for entry in resources.files(MIGRATIONS_PACKAGE).iterdir():
        if entry.name.endswith(".sql"):
            found.append((entry.name, entry.read_text(encoding="utf-8")))
    return sorted(found)


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply every migration not yet recorded. Returns the names newly applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migration ("
        "  name TEXT PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )
    conn.commit()
    already = {str(row["name"]) for row in conn.execute("SELECT name FROM schema_migration")}

    applied: list[str] = []
    for name, sql in _migration_files():
        if name in already:
            continue
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_migration (name) VALUES (?)", (name,))
        conn.commit()
        applied.append(name)
    return applied


def open_migrated(db_path: Path) -> sqlite3.Connection:
    """Connect and bring the schema up to date. The normal entry point."""
    conn = connect(db_path)
    migrate(conn)
    return conn
