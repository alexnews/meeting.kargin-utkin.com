"""Stage: transcript.

The fast path reads the .vtt Teams writes alongside its own recording, which
already carries real participant names. Only when there is no transcript does
this fall back to transcribing the audio locally, which costs a model download
and loses the names.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from meetinglens.config import Settings
from meetinglens.errors import StageError
from meetinglens.media.ffmpeg import extract_audio
from meetinglens.session import Session
from meetinglens.stages.base import is_done, require_meeting, running
from meetinglens.vtt import Cue, merge_adjacent, parse_vtt_file

STAGE = "transcript"

# Teams emits a cue every few seconds. Joining consecutive cues from one speaker
# below this gap turns stutter into paragraphs.
MERGE_GAP_MS = 2000

UNKNOWN_SPEAKER = "Unknown"

# Two devices captured separately is the whole diarization strategy: the
# microphone is the user, the meeting application's output is everybody else.
TRACK_SPEAKERS = {"mic": "You", "system": "Others"}

ASR_MISSING = (
    "no transcript supplied and faster-whisper is not installed, so this meeting\n"
    "           has slides but no speech. Export the transcript from Teams and pass it\n"
    '           with --transcript, or install the fallback: uv tool install "meetinglens[asr]"'
)


class TranscriptUnavailable(StageError):
    """No transcript to work from. Slides are still worth exporting."""


def _load_model(model_name: str) -> object:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptUnavailable(ASR_MISSING) from exc
    return WhisperModel(model_name, device="auto", compute_type="int8")


def _transcribe_file(model: object, audio: Path, speaker: str | None) -> list[Cue]:
    segments, _ = model.transcribe(str(audio), vad_filter=True)  # type: ignore[attr-defined]
    return [
        Cue(
            start_ms=int(segment.start * 1000),
            end_ms=int(segment.end * 1000),
            speaker=speaker,
            text=segment.text.strip(),
        )
        for segment in segments
        if segment.text.strip()
    ]


def _transcribe_locally(video: Path, model_name: str) -> list[Cue]:
    """Fallback for a video with no transcript. Speaker names are lost."""
    model = _load_model(model_name)
    with tempfile.TemporaryDirectory() as scratch:
        audio = Path(scratch) / "audio.wav"
        extract_audio(video, audio)
        return _transcribe_file(model, audio, None)


def transcribe_session(session: Session, model_name: str) -> list[Cue]:
    """Transcribe each captured track, labelling by which device it came from."""
    model = _load_model(model_name)
    cues: list[Cue] = []
    for track, audio in session.audio_tracks:
        cues.extend(_transcribe_file(model, audio, TRACK_SPEAKERS.get(track, UNKNOWN_SPEAKER)))
    return sorted(cues, key=lambda cue: cue.start_ms)


def _speaker_ids(
    conn: sqlite3.Connection, meeting_id: int, cues: list[Cue], self_name: str | None
) -> dict[str, int]:
    """Insert each distinct speaker once, marking which one is the user."""
    names = sorted({cue.speaker or UNKNOWN_SPEAKER for cue in cues})
    lowered_self = self_name.strip().lower() if self_name else None

    ids: dict[str, int] = {}
    for name in names:
        is_self = 1 if lowered_self and name.lower() == lowered_self else 0
        cursor = conn.execute(
            "INSERT INTO speaker (meeting_id, display_name, is_self) VALUES (?, ?, ?)",
            (meeting_id, name, is_self),
        )
        ids[name] = int(cursor.lastrowid or 0)
    return ids


def model_name() -> str:
    """Default to `base`: about 150 MB, against 500 MB for `small`."""
    return os.environ.get("MEETINGLENS_ASR_MODEL", "base")


def run_session(
    conn: sqlite3.Connection,
    settings: Settings,
    session: Session,
    meeting_id: int,
    *,
    force: bool = False,
) -> int:
    """Transcribe a captured session. Returns how many utterances were written."""
    require_meeting(conn, meeting_id)
    if not force and is_done(conn, meeting_id, STAGE):
        row = conn.execute(
            "SELECT count(*) AS n FROM utterance WHERE meeting_id = ?", (meeting_id,)
        ).fetchone()
        return int(row["n"])

    with running(conn, meeting_id, STAGE):
        conn.execute("DELETE FROM utterance WHERE meeting_id = ?", (meeting_id,))
        conn.execute("DELETE FROM speaker WHERE meeting_id = ?", (meeting_id,))

        cues = merge_adjacent(transcribe_session(session, model_name()), max_gap_ms=MERGE_GAP_MS)
        names = sorted({cue.speaker or UNKNOWN_SPEAKER for cue in cues})
        ids: dict[str, int] = {}
        for name in names:
            cursor = conn.execute(
                "INSERT INTO speaker (meeting_id, display_name, is_self) VALUES (?, ?, ?)",
                (meeting_id, name, 1 if name == TRACK_SPEAKERS["mic"] else 0),
            )
            ids[name] = int(cursor.lastrowid or 0)

        conn.executemany(
            "INSERT INTO utterance (meeting_id, start_ms, end_ms, speaker_id, text, source)"
            " VALUES (?, ?, ?, ?, ?, 'asr')",
            [
                (
                    meeting_id,
                    cue.start_ms,
                    cue.end_ms,
                    ids[cue.speaker or UNKNOWN_SPEAKER],
                    cue.text,
                )
                for cue in cues
            ],
        )
        conn.commit()
    return len(cues)


def run(
    conn: sqlite3.Connection,
    settings: Settings,
    meeting_id: int,
    *,
    force: bool = False,
) -> int:
    """Populate speakers and utterances. Returns how many utterances were written."""
    meeting = require_meeting(conn, meeting_id)
    if not force and is_done(conn, meeting_id, STAGE):
        row = conn.execute(
            "SELECT count(*) AS n FROM utterance WHERE meeting_id = ?", (meeting_id,)
        ).fetchone()
        return int(row["n"])

    transcript_path = meeting["transcript_path"]

    with running(conn, meeting_id, STAGE):
        conn.execute("DELETE FROM utterance WHERE meeting_id = ?", (meeting_id,))
        conn.execute("DELETE FROM speaker WHERE meeting_id = ?", (meeting_id,))

        if transcript_path:
            cues = merge_adjacent(
                parse_vtt_file(Path(str(transcript_path))), max_gap_ms=MERGE_GAP_MS
            )
            source = "vtt"
        else:
            cues = merge_adjacent(
                _transcribe_locally(Path(str(meeting["source_path"])), model_name()),
                max_gap_ms=MERGE_GAP_MS,
            )
            source = "asr"

        ids = _speaker_ids(conn, meeting_id, cues, settings.self_name)
        conn.executemany(
            "INSERT INTO utterance (meeting_id, start_ms, end_ms, speaker_id, text, source)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    meeting_id,
                    cue.start_ms,
                    cue.end_ms,
                    ids[cue.speaker or UNKNOWN_SPEAKER],
                    cue.text,
                    source,
                )
                for cue in cues
            ],
        )
        conn.commit()

    return len(cues)
