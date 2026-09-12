"""The keyframe stage against a real encoded video, end to end through ffmpeg."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from meetinglens.config import Settings
from meetinglens.stages import ingest, keyframes
from tests.slides import render_slide
from tests.video import Scene, write_video

ROADMAP = ["Migrate warehouse", "Kill legacy API", "Pricing model", "Hire two engineers"]
REVENUE = ["Q1 up 12 percent", "Q2 flat", "Q3 down on churn"]


def _two_slide_recording(path: Path) -> Path:
    return write_video(
        path,
        [
            Scene(render_slide("Q3 Roadmap", ROADMAP[:2]), 4),
            Scene(render_slide("Q3 Roadmap", ROADMAP), 4),
            Scene(render_slide("Revenue", REVENUE), 5),
        ],
    )


def test_a_two_slide_recording_yields_two_keyframes(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    """The roadmap build is one keyframe; revenue is the second.

    The first two scenes are the same slide gaining bullets, which stays inside
    the hash threshold and must therefore not split into two keyframes.
    """
    video = _two_slide_recording(tmp_path / "sync.mp4")
    meeting_id = ingest.run(conn, video, title="Weekly Sync")
    kept = keyframes.run(conn, settings, meeting_id)

    assert kept == 2
    rows = conn.execute(
        "SELECT start_ms, end_ms, image_path FROM keyframe WHERE meeting_id = ? ORDER BY start_ms",
        (meeting_id,),
    ).fetchall()
    assert rows[0]["start_ms"] == 0
    assert rows[1]["start_ms"] == pytest.approx(8000, abs=1500)
    for row in rows:
        assert Path(row["image_path"]).exists()
        with Image.open(row["image_path"]) as image:
            assert image.format == "WEBP"


def test_the_kept_image_is_the_finished_build_not_the_first_step(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    """The roadmap keyframe must show four bullets, not two.

    Compared by perceptual hash against both rendered states, so it asserts the
    behaviour rather than the pixels.
    """
    from meetinglens.media.dhash import dhash_from_gray, hamming
    from tests.slides import as_sampled_gray

    video = _two_slide_recording(tmp_path / "sync.mp4")
    meeting_id = ingest.run(conn, video, title="Weekly Sync")
    keyframes.run(conn, settings, meeting_id)

    first = conn.execute(
        "SELECT image_path FROM keyframe WHERE meeting_id = ? ORDER BY start_ms LIMIT 1",
        (meeting_id,),
    ).fetchone()
    with Image.open(first["image_path"]) as saved:
        kept = dhash_from_gray(as_sampled_gray(saved.convert("RGB")))

    partial = dhash_from_gray(as_sampled_gray(render_slide("Q3 Roadmap", ROADMAP[:2])))
    complete = dhash_from_gray(as_sampled_gray(render_slide("Q3 Roadmap", ROADMAP)))
    assert hamming(kept, complete) < hamming(kept, partial), (
        "the stored image is closer to the two-bullet state than the finished slide"
    )


def test_running_the_stage_twice_changes_nothing(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    video = _two_slide_recording(tmp_path / "sync.mp4")
    meeting_id = ingest.run(conn, video, title="Weekly Sync")

    keyframes.run(conn, settings, meeting_id)
    before = conn.execute(
        "SELECT start_ms, end_ms, dhash FROM keyframe WHERE meeting_id = ? ORDER BY start_ms",
        (meeting_id,),
    ).fetchall()

    keyframes.run(conn, settings, meeting_id, force=True)
    after = conn.execute(
        "SELECT start_ms, end_ms, dhash FROM keyframe WHERE meeting_id = ? ORDER BY start_ms",
        (meeting_id,),
    ).fetchall()

    assert [tuple(r) for r in before] == [tuple(r) for r in after]


def test_ingest_records_the_duration(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    video = _two_slide_recording(tmp_path / "sync.mp4")
    meeting_id = ingest.run(conn, video, title="Weekly Sync")
    row = conn.execute(
        "SELECT duration_ms, title FROM meeting WHERE id = ?", (meeting_id,)
    ).fetchone()
    assert row["title"] == "Weekly Sync"
    assert row["duration_ms"] == pytest.approx(13_000, abs=1200)
