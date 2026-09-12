"""Stage: ingest.

Probe the recording and write the meeting row. Cheap, and it is what every
later stage reads its paths from.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from meetinglens.media.ffmpeg import probe
from meetinglens.stages.base import running

STAGE = "ingest"


def _title_from(path: Path) -> str:
    """A filename turned into something readable."""
    stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return " ".join(part for part in stem.split() if part) or path.name


def _started_at(path: Path) -> str:
    stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return stamp.isoformat(timespec="seconds")


def run(
    conn: sqlite3.Connection,
    video: Path,
    *,
    transcript: Path | None = None,
    title: str | None = None,
) -> int:
    """Create or refresh the meeting row for this file. Returns the meeting id."""
    info = probe(video)
    resolved = str(video.resolve())

    existing = conn.execute("SELECT id FROM meeting WHERE source_path = ?", (resolved,)).fetchone()
    meeting_id = int(existing["id"]) if existing else 0

    if meeting_id == 0:
        cursor = conn.execute(
            "INSERT INTO meeting (title, source_path, transcript_path, started_at, duration_ms,"
            " status) VALUES (?, ?, ?, ?, ?, 'processing')",
            (
                title or _title_from(video),
                resolved,
                str(transcript.resolve()) if transcript else None,
                _started_at(video),
                info.duration_ms,
            ),
        )
        conn.commit()
        meeting_id = int(cursor.lastrowid or 0)

    with running(conn, meeting_id, STAGE):
        conn.execute(
            "UPDATE meeting SET title = ?, transcript_path = ?, duration_ms = ?,"
            " status = 'processing' WHERE id = ?",
            (
                title or _title_from(video),
                str(transcript.resolve()) if transcript else None,
                info.duration_ms,
                meeting_id,
            ),
        )
        conn.commit()
    return meeting_id
