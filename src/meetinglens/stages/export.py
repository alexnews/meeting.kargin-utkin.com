"""Stage: export.

One directory per meeting holding a markdown file and its images, so links are
relative and the whole thing can be dropped into Obsidian, a notes folder or a
repository without rewriting anything.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from meetinglens.align import Slide, Speech, timeline
from meetinglens.config import Settings
from meetinglens.stages.base import require_meeting, running

STAGE = "export"

_UNSAFE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ExportResult:
    directory: Path
    markdown: Path
    slides: int
    utterances: int


def slugify(value: str) -> str:
    cleaned = _UNSAFE.sub("-", value.casefold()).strip("-")
    return cleaned[:60] or "meeting"


def format_timestamp(ms: int, *, with_hours: bool) -> str:
    total_seconds, _ = divmod(max(ms, 0), 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if with_hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes + hours * 60:02d}:{seconds:02d}"


def _meeting_date(started_at: str | None) -> str:
    if not started_at:
        return datetime.now().strftime("%Y-%m-%d")
    try:
        return datetime.fromisoformat(started_at).strftime("%Y-%m-%d")
    except ValueError:
        return datetime.now().strftime("%Y-%m-%d")


def _headline(slide: Slide) -> str:
    """The slide's own first line, which is nearly always its title."""
    for line in slide.text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:80]
    return "untitled"


def _duration_phrase(duration_ms: int | None) -> str:
    if not duration_ms:
        return "unknown length"
    minutes = round(duration_ms / 60_000)
    return f"{minutes} min" if minutes else "under a minute"


def run(
    conn: sqlite3.Connection,
    settings: Settings,
    meeting_id: int,
    *,
    output_dir: Path | None = None,
) -> ExportResult:
    """Write the markdown file and its images. Always re-runs; it is cheap."""
    meeting = require_meeting(conn, meeting_id)
    title = str(meeting["title"])
    date = _meeting_date(meeting["started_at"])
    duration_ms = int(meeting["duration_ms"] or 0)
    with_hours = duration_ms >= 3_600_000

    base = output_dir or settings.output_dir
    directory = base / f"{date}-{slugify(title)}"
    images = directory / "keyframes"
    shutil.rmtree(directory, ignore_errors=True)
    images.mkdir(parents=True, exist_ok=True)

    with running(conn, meeting_id, STAGE):
        entries = timeline(conn, meeting_id)
        slides = [entry for entry in entries if isinstance(entry, Slide)]
        speech = [entry for entry in entries if isinstance(entry, Speech)]

        copied: dict[int, str] = {}
        for position, slide in enumerate(slides):
            if slide.image_path.exists():
                name = f"{position:04d}.webp"
                shutil.copy2(slide.image_path, images / name)
                copied[slide.keyframe_id] = f"keyframes/{name}"

        lines: list[str] = [
            f"# {title}",
            "",
            f"{date} | {_duration_phrase(duration_ms)} | {len(slides)} slides"
            f" | {len(speech)} turns",
            "",
        ]

        if len(slides) > 1:
            lines.append("## Slides")
            lines.append("")
            for slide in slides:
                stamp = format_timestamp(slide.at_ms, with_hours=with_hours)
                lines.append(f"- `{stamp}` {_headline(slide)}")
            lines.append("")

        lines.append("## Timeline")
        lines.append("")

        for entry in entries:
            stamp = format_timestamp(entry.at_ms, with_hours=with_hours)
            if isinstance(entry, Slide):
                lines.append(f"### `{stamp}` {_headline(entry)}")
                lines.append("")
                relative = copied.get(entry.keyframe_id)
                if relative:
                    lines.append(f"![{_headline(entry)}]({relative})")
                    lines.append("")
                for line in entry.text.splitlines():
                    if line.strip():
                        lines.append(f"> {line.strip()}")
                lines.append("")
            else:
                who = f"{entry.speaker} (you)" if entry.is_self else entry.speaker
                lines.append(f"**`{stamp}` {who}:** {entry.text}")
                lines.append("")

        markdown = directory / f"{date}-{slugify(title)}.md"
        markdown.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        conn.execute("UPDATE meeting SET status = 'done' WHERE id = ?", (meeting_id,))
        conn.commit()

    return ExportResult(
        directory=directory, markdown=markdown, slides=len(slides), utterances=len(speech)
    )
