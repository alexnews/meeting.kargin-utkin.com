"""Stage: ocr, and the two passes that decide which keyframes are worth keeping.

Doing this after text extraction rather than on pixel statistics is both simpler
and more reliable. Two rules replace four separate detectors:

**Text density.** A frame with almost no text is worthless as a note and is a
privacy problem besides. One threshold removes gallery view, the idle desktop
and video playback at once, and means faces are never written to an export.

**Superset merge.** If a frame's text contains the previous frame's text, the
earlier one was an intermediate state of a slide that was still building. Drop
it and extend the later frame back over its span.

Dropped frames are marked, not deleted, so a threshold can be retuned and the
export re-run without re-decoding the video.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from meetinglens.config import Settings
from meetinglens.media.ocr import read_image
from meetinglens.stages.base import is_done, require_meeting, running

STAGE = "ocr"


@dataclass
class _Frame:
    id: int
    start_ms: int
    text: str
    coverage: float
    lines: frozenset[str]


def _line_set(text: str) -> frozenset[str]:
    """Normalised lines, so spacing and case do not defeat the comparison."""
    return frozenset(
        " ".join(line.split()).casefold() for line in text.splitlines() if line.strip()
    )


def run(
    conn: sqlite3.Connection,
    settings: Settings,
    meeting_id: int,
    *,
    force: bool = False,
) -> int:
    """Read every keyframe, then apply both passes. Returns how many were kept."""
    require_meeting(conn, meeting_id)
    if not force and is_done(conn, meeting_id, STAGE):
        row = conn.execute(
            "SELECT count(*) AS n FROM keyframe WHERE meeting_id = ? AND dropped = 0",
            (meeting_id,),
        ).fetchone()
        return int(row["n"])

    with running(conn, meeting_id, STAGE):
        rows = conn.execute(
            "SELECT id, start_ms, image_path FROM keyframe WHERE meeting_id = ? ORDER BY start_ms",
            (meeting_id,),
        ).fetchall()

        frames: list[_Frame] = []
        for row in rows:
            result = read_image(Path(str(row["image_path"])))
            conn.execute(
                "UPDATE keyframe SET ocr_text = ?, text_coverage = ?, dropped = 0,"
                " drop_reason = NULL WHERE id = ?",
                (result.text, result.coverage, row["id"]),
            )
            frames.append(
                _Frame(
                    id=int(row["id"]),
                    start_ms=int(row["start_ms"]),
                    text=result.text,
                    coverage=result.coverage,
                    lines=_line_set(result.text),
                )
            )

        dropped: list[tuple[int, str]] = []
        survivors: list[_Frame] = []
        for frame in frames:
            if len(frame.text.strip()) < settings.ocr_min_chars:
                dropped.append((frame.id, "low_text"))
            elif frame.coverage < settings.ocr_min_coverage:
                dropped.append((frame.id, "low_coverage"))
            else:
                survivors.append(frame)

        kept: list[_Frame] = []
        for frame in survivors:
            previous = kept[-1] if kept else None
            if previous is not None and previous.lines and previous.lines <= frame.lines:
                dropped.append((previous.id, "superset"))
                frame.start_ms = previous.start_ms
                kept[-1] = frame
            else:
                kept.append(frame)

        for frame_id, reason in dropped:
            conn.execute(
                "UPDATE keyframe SET dropped = 1, drop_reason = ? WHERE id = ?",
                (reason, frame_id),
            )
        for frame in kept:
            conn.execute(
                "UPDATE keyframe SET start_ms = ? WHERE id = ?", (frame.start_ms, frame.id)
            )
        conn.commit()

    return len(kept)
