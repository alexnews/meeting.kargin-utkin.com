"""OCR, reading order, and the two passes that decide what survives."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw

from meetinglens.config import Settings
from meetinglens.stages import ingest, ocr
from tests.slides import render_slide
from tests.video import Scene, write_video

ROADMAP = ["Migrate warehouse", "Kill legacy API", "Pricing model", "Hire two engineers"]


def _meeting_with_frames(
    conn: sqlite3.Connection, tmp_path: Path, images: list[Image.Image]
) -> int:
    """Insert keyframes directly, so OCR is tested without re-encoding video."""
    video = write_video(tmp_path / "sync.mp4", [Scene(render_slide("x", ["y"]), 2)])
    meeting_id = ingest.run(conn, video, title="Sync")
    folder = tmp_path / "frames"
    folder.mkdir(exist_ok=True)
    for position, image in enumerate(images):
        path = folder / f"{position:04d}.webp"
        image.convert("RGB").save(path, "WEBP", quality=80)
        conn.execute(
            "INSERT INTO keyframe (meeting_id, start_ms, end_ms, image_path, dhash)"
            " VALUES (?, ?, ?, ?, ?)",
            (meeting_id, position * 10_000, (position + 1) * 10_000, str(path), "00" * 72),
        )
    conn.commit()
    return meeting_id


def _gallery_view() -> Image.Image:
    """What Teams shows with nobody sharing: tiles with small name labels."""
    image = Image.new("RGB", (1280, 720), (32, 32, 36))
    draw = ImageDraw.Draw(image)
    from tests.slides import _font

    for row in range(2):
        for column in range(2):
            x, y = 60 + column * 620, 60 + row * 320
            draw.rectangle([(x, y), (x + 560, y + 280)], fill=(70, 74, 84))
            draw.text(
                (x + 16, y + 248),
                f"Person {row * 2 + column + 1}",
                fill=(230, 230, 230),
                font=_font(24),
            )
    return image


def test_a_slide_reads_in_order(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    meeting_id = _meeting_with_frames(conn, tmp_path, [render_slide("Q3 Roadmap", ROADMAP)])
    assert ocr.run(conn, settings, meeting_id) == 1

    text = conn.execute(
        "SELECT ocr_text FROM keyframe WHERE meeting_id = ?", (meeting_id,)
    ).fetchone()["ocr_text"]
    lines = text.splitlines()
    assert lines[0] == "Q3 Roadmap"
    assert "Migrate warehouse" in lines[1]
    assert "Hire two engineers" in lines[-1]


def test_a_gallery_of_faces_is_dropped(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    """The privacy control. Frames of people must never reach an export."""
    meeting_id = _meeting_with_frames(
        conn, tmp_path, [render_slide("Q3 Roadmap", ROADMAP), _gallery_view()]
    )
    assert ocr.run(conn, settings, meeting_id) == 1

    rows = conn.execute(
        "SELECT dropped, drop_reason, text_coverage FROM keyframe WHERE meeting_id = ?"
        " ORDER BY start_ms",
        (meeting_id,),
    ).fetchall()
    assert rows[0]["dropped"] == 0
    assert rows[1]["dropped"] == 1
    assert rows[1]["drop_reason"] in {"low_text", "low_coverage"}
    assert rows[0]["text_coverage"] > rows[1]["text_coverage"]


def test_a_build_collapses_into_the_finished_slide(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    """Two keyframes where the second contains the first: keep only the second."""
    meeting_id = _meeting_with_frames(
        conn,
        tmp_path,
        [render_slide("Q3 Roadmap", ROADMAP[:2]), render_slide("Q3 Roadmap", ROADMAP)],
    )
    assert ocr.run(conn, settings, meeting_id) == 1

    kept = conn.execute(
        "SELECT start_ms, ocr_text FROM keyframe WHERE meeting_id = ? AND dropped = 0",
        (meeting_id,),
    ).fetchone()
    assert kept["start_ms"] == 0, "the survivor must cover the dropped frame's span"
    assert "Hire two engineers" in kept["ocr_text"]

    reason = conn.execute(
        "SELECT drop_reason FROM keyframe WHERE meeting_id = ? AND dropped = 1", (meeting_id,)
    ).fetchone()
    assert reason["drop_reason"] == "superset"


def test_two_different_slides_both_survive(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    meeting_id = _meeting_with_frames(
        conn,
        tmp_path,
        [
            render_slide("Q3 Roadmap", ROADMAP),
            render_slide("Revenue", ["Q1 up 12 percent", "Q2 flat", "Q3 down on churn"]),
        ],
    )
    assert ocr.run(conn, settings, meeting_id) == 2


def test_running_twice_leaves_the_same_decisions(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    meeting_id = _meeting_with_frames(
        conn,
        tmp_path,
        [render_slide("Q3 Roadmap", ROADMAP[:2]), render_slide("Q3 Roadmap", ROADMAP)],
    )
    query = (
        "SELECT start_ms, dropped, drop_reason, ocr_text FROM keyframe"
        " WHERE meeting_id = ? ORDER BY id"
    )
    ocr.run(conn, settings, meeting_id)
    before = [tuple(r) for r in conn.execute(query, (meeting_id,))]
    ocr.run(conn, settings, meeting_id, force=True)
    after = [tuple(r) for r in conn.execute(query, (meeting_id,))]
    assert before == after


def test_a_high_threshold_drops_everything(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    """Thresholds are tunable and dropping is reversible, not destructive."""
    meeting_id = _meeting_with_frames(conn, tmp_path, [render_slide("Q3 Roadmap", ROADMAP)])
    assert ocr.run(conn, settings, meeting_id, force=True) == 1
    strict = replace(settings, ocr_min_chars=10_000)
    assert ocr.run(conn, strict, meeting_id, force=True) == 0
    assert ocr.run(conn, settings, meeting_id, force=True) == 1, "retuning must be reversible"
