"""The whole tool: a recording and a transcript in, a markdown file out."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from meetinglens.config import Settings
from meetinglens.stages import export, ingest, keyframes, ocr
from meetinglens.stages import transcript as transcript_stage
from tests.slides import render_slide
from tests.video import Scene, write_video

ROADMAP = ["Migrate warehouse", "Kill legacy API", "Pricing model", "Hire two engineers"]
REVENUE = ["Q1 up 12 percent", "Q2 flat", "Q3 down on churn"]

VTT = """WEBVTT

00:00:01.000 --> 00:00:05.000
<v Alex Kargin>Let us start with the roadmap for the quarter.</v>

00:00:06.000 --> 00:00:09.500
<v Sarah Chen>So yeah, these are the priorities.</v>

00:00:10.000 --> 00:00:12.000
<v Alex Kargin>Who owns the second one?</v>

00:00:13.000 --> 00:00:16.000
<v Sarah Chen>Revenue is the other thing we need to cover.</v>
"""


def _recording(tmp_path: Path) -> tuple[Path, Path]:
    video = write_video(
        tmp_path / "weekly sync.mp4",
        [
            Scene(render_slide("Q3 Roadmap", ROADMAP[:2]), 4),
            Scene(render_slide("Q3 Roadmap", ROADMAP), 5),
            Scene(render_slide("Revenue", REVENUE), 5),
        ],
    )
    vtt = tmp_path / "weekly sync.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    return video, vtt


def _pipeline(conn: sqlite3.Connection, settings: Settings, tmp_path: Path) -> export.ExportResult:
    video, vtt = _recording(tmp_path)
    meeting_id = ingest.run(conn, video, transcript=vtt)
    keyframes.run(conn, settings, meeting_id)
    transcript_stage.run(conn, settings, meeting_id)
    ocr.run(conn, settings, meeting_id)
    return export.run(conn, settings, meeting_id)


def test_a_recording_becomes_a_readable_markdown_file(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    result = _pipeline(conn, replace(settings, self_name="Alex Kargin"), tmp_path)
    text = result.markdown.read_text(encoding="utf-8")

    # The filename came from the recording, spaces and all.
    assert result.markdown.name.endswith("weekly-sync.md")

    # Both slides survive, the roadmap build having collapsed into one.
    assert result.slides == 2
    assert "Q3 Roadmap" in text
    assert "Revenue" in text

    # Slide text is quoted, including the bullet that was never spoken aloud.
    assert "> 4. Hire two engineers" in text

    # Speech is attributed, and the user is marked.
    assert "Alex Kargin (you):** Let us start with the roadmap" in text
    assert "Sarah Chen:** So yeah, these are the priorities." in text

    # Images are relative and actually present.
    assert "](keyframes/0000.webp)" in text
    assert (result.directory / "keyframes" / "0000.webp").exists()


def test_the_timeline_interleaves_slides_and_speech_in_order(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    result = _pipeline(conn, settings, tmp_path)
    lines = result.markdown.read_text(encoding="utf-8").splitlines()
    timeline_at = lines.index("## Timeline")
    body = [line for line in lines[timeline_at:] if line.startswith(("### ", "**`"))]

    # The first thing is a slide, and speech follows it rather than preceding it.
    assert body[0].startswith("### ")
    assert any(line.startswith("**`") for line in body[1:])

    stamps = [line.split("`")[1] for line in body]
    assert stamps == sorted(stamps), "entries must run in chronological order"


def test_exporting_twice_produces_the_same_document(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    first = _pipeline(conn, settings, tmp_path)
    original = first.markdown.read_text(encoding="utf-8")

    meeting_id = conn.execute("SELECT id FROM meeting").fetchone()["id"]
    again = export.run(conn, settings, meeting_id)
    assert again.markdown.read_text(encoding="utf-8") == original


def test_a_meeting_with_no_transcript_still_exports_its_slides(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    """Transcription is skipped here; slides alone must still produce a document."""
    video, _ = _recording(tmp_path)
    meeting_id = ingest.run(conn, video, title="Slides Only")
    keyframes.run(conn, settings, meeting_id)
    ocr.run(conn, settings, meeting_id)
    result = export.run(conn, settings, meeting_id)

    text = result.markdown.read_text(encoding="utf-8")
    assert result.slides == 2
    assert result.utterances == 0
    assert "Hire two engineers" in text
