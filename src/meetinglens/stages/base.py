"""Stage bookkeeping against the job table.

Every stage is idempotent: running it twice leaves the database in the same
state as running it once. Stages achieve that by clearing their own output
before writing it, so there is no partial-write recovery to reason about.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from meetinglens.errors import StageError


def is_done(conn: sqlite3.Connection, meeting_id: int, stage: str) -> bool:
    row = conn.execute(
        "SELECT status FROM job WHERE meeting_id = ? AND stage = ?", (meeting_id, stage)
    ).fetchone()
    return row is not None and row["status"] == "done"


@contextmanager
def running(conn: sqlite3.Connection, meeting_id: int, stage: str) -> Iterator[None]:
    """Mark a stage running, then done, or failed with the error recorded."""
    conn.execute(
        "INSERT INTO job (meeting_id, stage, status, attempts, started_at)"
        " VALUES (?, ?, 'running', 1, datetime('now'))"
        " ON CONFLICT (meeting_id, stage) DO UPDATE SET"
        "   status = 'running',"
        "   attempts = job.attempts + 1,"
        "   error = NULL,"
        "   started_at = datetime('now'),"
        "   finished_at = NULL",
        (meeting_id, stage),
    )
    conn.commit()
    try:
        yield
    except Exception as exc:
        conn.execute(
            "UPDATE job SET status = 'failed', error = ?, finished_at = datetime('now')"
            " WHERE meeting_id = ? AND stage = ?",
            (str(exc)[:2000], meeting_id, stage),
        )
        conn.commit()
        raise
    conn.execute(
        "UPDATE job SET status = 'done', error = NULL, finished_at = datetime('now')"
        " WHERE meeting_id = ? AND stage = ?",
        (meeting_id, stage),
    )
    conn.commit()


def require_meeting(conn: sqlite3.Connection, meeting_id: int) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM meeting WHERE id = ?", (meeting_id,)
    ).fetchone()
    if row is None:
        raise StageError(f"no meeting with id {meeting_id}")
    return row
