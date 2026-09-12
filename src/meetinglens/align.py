"""Interleave what was said with what was on screen.

Not a stage: there is nothing to store. Both sides already carry millisecond
offsets, so the timeline is a query, and keeping it derived means a threshold
change in the OCR pass shows up in the next export with no re-run.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Slide:
    at_ms: int
    end_ms: int
    keyframe_id: int
    image_path: Path
    text: str


@dataclass(frozen=True)
class Speech:
    at_ms: int
    end_ms: int
    speaker: str
    is_self: bool
    text: str


Entry = Slide | Speech


def timeline(conn: sqlite3.Connection, meeting_id: int) -> list[Entry]:
    """Every surviving keyframe and every utterance, in the order they happened.

    A slide sorts before speech at the same instant, because the screen changing
    is what the next sentence is about.
    """
    slides = [
        Slide(
            at_ms=int(row["start_ms"]),
            end_ms=int(row["end_ms"]),
            keyframe_id=int(row["id"]),
            image_path=Path(str(row["image_path"])),
            text=str(row["ocr_text"] or ""),
        )
        for row in conn.execute(
            "SELECT id, start_ms, end_ms, image_path, ocr_text FROM keyframe"
            " WHERE meeting_id = ? AND dropped = 0 ORDER BY start_ms",
            (meeting_id,),
        )
    ]

    speech = [
        Speech(
            at_ms=int(row["start_ms"]),
            end_ms=int(row["end_ms"]),
            speaker=str(row["display_name"] or "Unknown"),
            is_self=bool(row["is_self"]),
            text=str(row["text"]),
        )
        for row in conn.execute(
            "SELECT u.start_ms, u.end_ms, u.text, s.display_name, s.is_self"
            " FROM utterance u LEFT JOIN speaker s ON s.id = u.speaker_id"
            " WHERE u.meeting_id = ? ORDER BY u.start_ms",
            (meeting_id,),
        )
    ]

    entries: list[Entry] = [*slides, *speech]
    entries.sort(key=lambda entry: (entry.at_ms, 0 if isinstance(entry, Slide) else 1))
    return entries


def spoken_during(entries: list[Entry], slide: Slide) -> list[Speech]:
    """Everything said while a slide was on screen."""
    return [
        entry
        for entry in entries
        if isinstance(entry, Speech) and entry.at_ms < slide.end_ms and entry.end_ms > slide.at_ms
    ]
