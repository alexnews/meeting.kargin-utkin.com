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
from meetinglens.stages.base import is_done, require_meeting, running
from meetinglens.vtt import Cue, merge_adjacent, parse_vtt_file

STAGE = "transcript"

# Teams emits a cue every few seconds. Joining consecutive cues from one speaker
# below this gap turns stutter into paragraphs.
MERGE_GAP_MS = 2000

UNKNOWN_SPEAKER = "Unknown"

ASR_MISSING = (
    "No transcript was supplied and faster-whisper is not installed.\n"
    "Either export the transcript from Teams and pass it with --transcript,\n"
    'or install the fallback: uv tool install "meetinglens[asr]"'
)


def _transcribe_locally(video: Path, model_name: str) -> list[Cue]:
    """Fallback for meetings with no Teams transcript. Speaker names are lost."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise StageError(ASR_MISSING) from exc

    with tempfile.TemporaryDirectory() as scratch:
        audio = Path(scratch) / "audio.wav"
        extract_audio(video, audio)
        model = WhisperModel(model_name, device="auto", compute_type="int8")
        segments, _ = model.transcribe(str(audio), vad_filter=True)
        return [
            Cue(
                start_ms=int(segment.start * 1000),
                end_ms=int(segment.end * 1000),
                speaker=None,
                text=segment.text.strip(),
            )
            for segment in segments
            if segment.text.strip()
        ]


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
            model_name = os.environ.get("MEETINGLENS_ASR_MODEL", "small")
            cues = merge_adjacent(
                _transcribe_locally(Path(str(meeting["source_path"])), model_name),
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
