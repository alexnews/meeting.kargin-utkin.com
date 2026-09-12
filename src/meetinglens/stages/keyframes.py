"""Stage: keyframes.

Decode the video once at a low frame rate, hash every sampled frame, and commit
a keyframe only when the screen has held still long enough to be worth keeping.

The state machine is a pure function over a sequence of hashes so it can be
tested without a video file. See tests/test_keyframe_detect.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from meetinglens.media.dhash import hamming


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
