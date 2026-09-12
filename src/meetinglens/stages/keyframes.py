"""Stage: keyframes.

Decode the video once at a low frame rate, hash every sampled frame, and commit
a keyframe only when the screen has held still long enough to be worth keeping.

The state machine is a pure function over a sequence of hashes so it can be
tested without a video file. See tests/test_keyframe_detect.py.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from meetinglens.config import Settings
from meetinglens.media.dhash import dhash_from_gray, hamming, to_hex
from meetinglens.media.ffmpeg import extract_still, sample_gray_frames
from meetinglens.stages.base import is_done, require_meeting, running

STAGE = "keyframes"

# Side of the square grayscale frame the decoder hands the hasher. Large enough
# that a 24x24 hash has real detail to work with, small enough that an hour of
# video is tens of megabytes through a pipe rather than gigabytes.
SAMPLE_SIDE = 128


@dataclass(frozen=True)
class DetectedKeyframe:
    """One committed screen state.

    frame_index is the LAST sampled frame that matched this keyframe, not the
    first. On a slide that builds one bullet at a time the individual steps stay
    within the hash threshold, so the whole build is a single keyframe; taking
    the last matching frame means the image is the finished slide rather than
    the slide with one bullet on it.
    """

    frame_index: int
    start_ms: int
    end_ms: int
    dhash: int


@dataclass
class _Open:
    """A committed keyframe still accumulating frames."""

    frame_index: int
    start_ms: int
    end_ms: int
    dhash: int


@dataclass
class _Candidate:
    """A screen state that has changed but not yet held still long enough."""

    dhash: int
    first_ms: int
    last_ms: int


def detect(
    hashes: Sequence[int],
    *,
    frame_interval_ms: int,
    threshold: int,
    stability_ms: int,
) -> list[DetectedKeyframe]:
    """Reduce a sequence of frame hashes to the screen states worth keeping.

    A frame within `threshold` bits of the open keyframe extends it. Anything
    else starts a candidate, and a candidate is committed once it has persisted
    for `stability_ms`. Mid-transition and crossfade frames never reach that,
    so they are discarded.
    """
    committed: list[_Open] = []
    current: _Open | None = None
    candidate: _Candidate | None = None

    for index, frame_hash in enumerate(hashes):
        start_of_frame = index * frame_interval_ms
        end_of_frame = start_of_frame + frame_interval_ms

        if current is not None and hamming(frame_hash, current.dhash) < threshold:
            # Same screen. Extend it, and forget any change that did not stick.
            current.end_ms = end_of_frame
            current.frame_index = index
            candidate = None
            continue

        if candidate is None or hamming(frame_hash, candidate.dhash) >= threshold:
            candidate = _Candidate(
                dhash=frame_hash, first_ms=start_of_frame, last_ms=start_of_frame
            )
        else:
            candidate.last_ms = start_of_frame

        held_for = candidate.last_ms - candidate.first_ms + frame_interval_ms
        if held_for < stability_ms:
            continue

        if current is not None:
            current.end_ms = candidate.first_ms
        current = _Open(
            frame_index=index,
            start_ms=candidate.first_ms,
            end_ms=end_of_frame,
            dhash=candidate.dhash,
        )
        committed.append(current)
        candidate = None

    return [
        DetectedKeyframe(
            frame_index=item.frame_index,
            start_ms=item.start_ms,
            end_ms=item.end_ms,
            dhash=item.dhash,
        )
        for item in committed
    ]


def run(
    conn: sqlite3.Connection,
    settings: Settings,
    meeting_id: int,
    *,
    force: bool = False,
) -> int:
    """Detect keyframes for a meeting and write them. Returns how many were kept.

    Idempotent: the stage clears its own output before writing, so running it
    twice leaves exactly the state running it once did.
    """
    meeting = require_meeting(conn, meeting_id)
    if not force and is_done(conn, meeting_id, STAGE):
        row = conn.execute(
            "SELECT count(*) AS n FROM keyframe WHERE meeting_id = ?", (meeting_id,)
        ).fetchone()
        return int(row["n"])

    video = Path(str(meeting["source_path"]))
    interval_ms = 1000 // settings.keyframe_fps
    images = settings.storage_dir / f"meeting-{meeting_id:06d}" / "keyframes"

    with running(conn, meeting_id, STAGE):
        hashes = [
            dhash_from_gray(frame)
            for frame in sample_gray_frames(video, fps=settings.keyframe_fps, side=SAMPLE_SIDE)
        ]
        found = detect(
            hashes,
            frame_interval_ms=interval_ms,
            threshold=settings.dhash_threshold,
            stability_ms=settings.stability_ms,
        )

        conn.execute("DELETE FROM keyframe WHERE meeting_id = ?", (meeting_id,))
        shutil.rmtree(images, ignore_errors=True)
        images.mkdir(parents=True, exist_ok=True)

        for position, keyframe in enumerate(found):
            destination = images / f"{position:04d}.webp"
            extract_still(
                video,
                at_ms=keyframe.frame_index * interval_ms,
                destination=destination,
                quality=settings.webp_quality,
            )
            conn.execute(
                "INSERT INTO keyframe (meeting_id, start_ms, end_ms, image_path, dhash)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    meeting_id,
                    keyframe.start_ms,
                    keyframe.end_ms,
                    str(destination),
                    to_hex(keyframe.dhash),
                ),
            )
        conn.commit()

    return len(found)
