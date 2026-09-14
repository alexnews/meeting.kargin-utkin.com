"""Stage: screens.

The counterpart to `keyframes` for a recorded session. Nothing needs detecting,
because capture already discarded everything that was not a distinct screen, so
this only writes the rows.
"""

from __future__ import annotations

import sqlite3

from meetinglens.media.dhash import to_hex
from meetinglens.session import Session
from meetinglens.stages.base import is_done, require_meeting, running

STAGE = "keyframes"  # same slot in the job table as the video path


def run(
    conn: sqlite3.Connection,
    session: Session,
    meeting_id: int,
    *,
    force: bool = False,
) -> int:
    """Write one keyframe row per captured screen. Returns how many."""
    require_meeting(conn, meeting_id)
    if not force and is_done(conn, meeting_id, STAGE):
        row = conn.execute(
            "SELECT count(*) AS n FROM keyframe WHERE meeting_id = ?", (meeting_id,)
        ).fetchone()
        return int(row["n"])

    with running(conn, meeting_id, STAGE):
        conn.execute("DELETE FROM keyframe WHERE meeting_id = ?", (meeting_id,))
        screens = session.screens
        for position, screen in enumerate(screens):
            is_last = position == len(screens) - 1
            end_ms = (
                max(session.duration_ms, screen.at_ms + 1000)
                if is_last
                else screens[position + 1].at_ms
            )
            conn.execute(
                "INSERT INTO keyframe (meeting_id, start_ms, end_ms, image_path, dhash)"
                " VALUES (?, ?, ?, ?, ?)",
                (meeting_id, screen.at_ms, end_ms, str(screen.path), to_hex(0)),
            )
        conn.commit()
    return len(session.screens)
