"""Find recordings the user already has, so nobody types a file path.

Teams downloads land in Downloads. The transcript arrives as a separate file
with the same name, so pairing them is a matter of matching the stem.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
TRANSCRIPT_SUFFIXES = (".vtt", ".srt")

SEARCH_DIRECTORIES = (
    Path.home() / "Downloads",
    Path.home() / "Desktop",
    Path.home() / "Movies",
    Path.home() / "Documents",
)


@dataclass(frozen=True)
class Recording:
    video: Path
    transcript: Path | None
    size_bytes: int
    modified_at: float

    @property
    def key(self) -> str:
        return str(self.video)

    @property
    def title(self) -> str:
        stem = self.video.stem.replace("_", " ").replace("-", " ").strip()
        return " ".join(stem.split()) or self.video.name


def _matching_transcript(video: Path) -> Path | None:
    """A transcript sitting next to the video with the same name."""
    for suffix in TRANSCRIPT_SUFFIXES:
        candidate = video.with_suffix(suffix)
        if candidate.exists():
            return candidate
    # Teams sometimes appends a suffix to one of the two files.
    for candidate in sorted(video.parent.glob(f"{video.stem}*")):
        if candidate.suffix.lower() in TRANSCRIPT_SUFFIXES:
            return candidate
    return None


def find_recordings(limit: int = 40) -> list[Recording]:
    """Videos in the usual places, newest first, paired with their transcripts."""
    seen: dict[Path, Recording] = {}
    for directory in SEARCH_DIRECTORIES:
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not path.is_file() or path.suffix.lower() not in VIDEO_SUFFIXES:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen[resolved] = Recording(
                video=path,
                transcript=_matching_transcript(path),
                size_bytes=stat.st_size,
                modified_at=stat.st_mtime,
            )

    newest_first = sorted(seen.values(), key=lambda item: item.modified_at, reverse=True)
    return newest_first[:limit]
