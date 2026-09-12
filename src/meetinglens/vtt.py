"""WebVTT parsing, aimed at what Microsoft Teams actually produces.

Teams varies by tenant: a GUID cue identifier may or may not be present, hours
may be omitted from timestamps, and the speaker may arrive as a voice span or a
bare name prefix. None of that is configurable by the user, so all of it is
handled here.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from meetinglens.errors import MeetingLensError

_TIMING = re.compile(
    r"^\s*(?P<start>\d{1,2}:\d{1,2}(?::\d{1,2})?[.,]\d{1,3})"
    r"\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{1,2}(?::\d{1,2})?[.,]\d{1,3})"
)
_VOICE = re.compile(r"^<v(?:\.[^\s>]+)?\s+(?P<speaker>[^>]+)>(?P<text>.*)$", re.DOTALL)
_TAG = re.compile(r"</?[^>]+>")
_NAME_PREFIX = re.compile(r"^(?P<speaker>[^:<>]{1,60}?):\s+(?P<text>\S.*)$", re.DOTALL)


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    speaker: str | None
    text: str


class TranscriptError(MeetingLensError):
    """The transcript file could not be parsed."""


def _timestamp_to_ms(value: str) -> int:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        hours, minutes, rest = "0", parts[0], parts[1]
    else:
        hours, minutes, rest = parts[0], parts[1], parts[2]
    seconds, _, fraction = rest.partition(".")
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1000
        + int(fraction.ljust(3, "0")[:3])
    )


def _clean(text: str) -> str:
    """Drop markup and collapse the whitespace a multi-line cue leaves behind."""
    return " ".join(_TAG.sub("", text).split())


def _blocks(content: str) -> list[list[str]]:
    normalised = content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return [
        [line for line in chunk.split("\n") if line.strip()]
        for chunk in normalised.split("\n\n")
        if chunk.strip()
    ]


def parse_vtt(content: str) -> list[Cue]:
    """Parse a WebVTT document into cues, dropping anything with no text."""
    raw: list[tuple[int, int, str | None, str]] = []

    for block in _blocks(content):
        if block[0].upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing_index = next((i for i, line in enumerate(block) if _TIMING.match(line)), None)
        if timing_index is None:
            continue
        timing = _TIMING.match(block[timing_index])
        assert timing is not None
        body = "\n".join(block[timing_index + 1 :]).strip()
        if not body:
            continue

        speaker: str | None = None
        voice = _VOICE.match(body)
        if voice is not None:
            speaker = voice.group("speaker").strip()
            body = voice.group("text")

        raw.append(
            (
                _timestamp_to_ms(timing.group("start")),
                _timestamp_to_ms(timing.group("end")),
                speaker,
                body,
            )
        )

    return _resolve_bare_prefixes(raw)


def _resolve_bare_prefixes(raw: list[tuple[int, int, str | None, str]]) -> list[Cue]:
    """Treat `Name: text` as a speaker only when the same prefix recurs.

    A one-off prefix is far more likely to be ordinary punctuation, as in
    "Note: the deadline moved", than a participant who spoke exactly once.
    """
    candidates = Counter(
        match.group("speaker").strip()
        for _, _, speaker, text in raw
        if speaker is None and (match := _NAME_PREFIX.match(_clean(text)))
    )
    recurring = {name for name, count in candidates.items() if count > 1}

    cues: list[Cue] = []
    for start_ms, end_ms, speaker, text in raw:
        cleaned = _clean(text)
        if speaker is None:
            match = _NAME_PREFIX.match(cleaned)
            if match is not None and match.group("speaker").strip() in recurring:
                speaker = match.group("speaker").strip()
                cleaned = match.group("text").strip()
        if not cleaned:
            continue
        cues.append(Cue(start_ms, end_ms, speaker, cleaned))
    return cues


def parse_vtt_file(path: Path) -> list[Cue]:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-16")
    except OSError as exc:
        raise TranscriptError(f"could not read {path}: {exc}") from exc
    return parse_vtt(content)


def merge_adjacent(cues: list[Cue], *, max_gap_ms: int) -> list[Cue]:
    """Join consecutive cues from one speaker into readable paragraphs.

    Teams emits a cue every few seconds, which reads as stutter in a document.
    A gap longer than max_gap_ms is treated as a new turn.
    """
    merged: list[Cue] = []
    for cue in cues:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.speaker == cue.speaker
            and cue.start_ms - previous.end_ms <= max_gap_ms
        ):
            merged[-1] = Cue(
                previous.start_ms,
                cue.end_ms,
                previous.speaker,
                f"{previous.text} {cue.text}",
            )
        else:
            merged.append(cue)
    return merged
