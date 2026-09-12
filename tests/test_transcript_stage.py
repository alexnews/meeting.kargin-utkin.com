"""The transcript stage: Teams cues become speakers and utterances."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from meetinglens.config import Settings
from meetinglens.stages import ingest, transcript
from tests.slides import render_slide
from tests.video import Scene, write_video

VTT = """WEBVTT

00:00:03.120 --> 00:00:07.440
<v Alex Kargin>So let us start with the roadmap.</v>

00:00:07.900 --> 00:00:09.400
<v Alex Kargin>There are four items.</v>

00:00:12.000 --> 00:00:15.000
<v Sarah Chen>Who owns the second one?</v>
"""


def _recording(tmp_path: Path, *, with_transcript: bool = True) -> tuple[Path, Path | None]:
    video = write_video(
        tmp_path / "sync.mp4", [Scene(render_slide("Q3 Roadmap", ["Migrate", "Retire"]), 4)]
    )
    if not with_transcript:
        return video, None
    vtt = tmp_path / "sync.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    return video, vtt


def test_cues_become_utterances_with_real_names(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    video, vtt = _recording(tmp_path)
    meeting_id = ingest.run(conn, video, transcript=vtt, title="Sync")
    written = transcript.run(conn, settings, meeting_id)

    assert written == 2, "the two adjacent Kargin cues should merge into one turn"
    rows = conn.execute(
        "SELECT u.start_ms, u.end_ms, u.text, u.source, s.display_name"
        " FROM utterance u JOIN speaker s ON s.id = u.speaker_id"
        " WHERE u.meeting_id = ? ORDER BY u.start_ms",
        (meeting_id,),
    ).fetchall()
    assert rows[0]["display_name"] == "Alex Kargin"
    assert rows[0]["text"] == "So let us start with the roadmap. There are four items."
    assert rows[0]["start_ms"] == 3120
    assert rows[0]["end_ms"] == 9400
    assert rows[0]["source"] == "vtt"
    assert rows[1]["display_name"] == "Sarah Chen"


def test_the_user_is_marked_when_their_name_is_configured(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    video, vtt = _recording(tmp_path)
    meeting_id = ingest.run(conn, video, transcript=vtt, title="Sync")
    transcript.run(conn, replace(settings, self_name="alex kargin"), meeting_id)

    rows = conn.execute(
        "SELECT display_name, is_self FROM speaker WHERE meeting_id = ? ORDER BY display_name",
        (meeting_id,),
    ).fetchall()
    marked = {row["display_name"]: row["is_self"] for row in rows}
    assert marked == {"Alex Kargin": 1, "Sarah Chen": 0}


def test_running_twice_leaves_the_same_rows(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    video, vtt = _recording(tmp_path)
    meeting_id = ingest.run(conn, video, transcript=vtt, title="Sync")

    transcript.run(conn, settings, meeting_id)
    query = "SELECT start_ms, end_ms, text FROM utterance WHERE meeting_id = ? ORDER BY start_ms"
    before = [tuple(r) for r in conn.execute(query, (meeting_id,))]
    transcript.run(conn, settings, meeting_id, force=True)
    after = [tuple(r) for r in conn.execute(query, (meeting_id,))]

    assert before == after
    speakers = conn.execute(
        "SELECT count(*) AS n FROM speaker WHERE meeting_id = ?", (meeting_id,)
    ).fetchone()
    assert speakers["n"] == 2, "a second run must not duplicate speakers"
