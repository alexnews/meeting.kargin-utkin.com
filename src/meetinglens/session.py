"""A recorded session on disk: audio tracks plus the screens that were kept.

This is the shape `meetinglens record` writes and the shape you can assemble by
hand from an OBS audio recording and a folder of screenshots.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from meetinglens.errors import StageError

SESSION_FILE = "session.json"
IMAGE_SUFFIXES = (".webp", ".png", ".jpg", ".jpeg")
AUDIO_SUFFIXES = (".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg")


@dataclass(frozen=True)
class Screen:
    path: Path
    at_ms: int


@dataclass(frozen=True)
class Session:
    directory: Path
    title: str
    started_at: str | None
    duration_ms: int
    mic_audio: Path | None
    system_audio: Path | None
    screens: list[Screen]

    @property
    def audio_tracks(self) -> list[tuple[str, Path]]:
        """(track name, file) for every track that exists."""
        found: list[tuple[str, Path]] = []
        if self.mic_audio is not None:
            found.append(("mic", self.mic_audio))
        if self.system_audio is not None:
            found.append(("system", self.system_audio))
        return found


def is_session(path: Path) -> bool:
    return path.is_dir() and (path / SESSION_FILE).exists()


def load(directory: Path) -> Session:
    """Read a session directory written by `record`."""
    manifest_path = directory / SESSION_FILE
    if not manifest_path.exists():
        raise StageError(f"{directory} is not a recording session: no {SESSION_FILE}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    screens_dir = directory / "screens"
    screens = [
        Screen(path=screens_dir / str(item["file"]), at_ms=int(item["atMs"]))
        for item in manifest.get("screens", [])
        if (screens_dir / str(item["file"])).exists()
    ]

    def track(name: str) -> Path | None:
        candidate = directory / f"audio_{name}.mp3"
        return candidate if candidate.exists() else None

    return Session(
        directory=directory,
        title=str(manifest.get("title") or directory.name),
        started_at=manifest.get("startedAt"),
        duration_ms=int(manifest.get("durationMs") or 0),
        mic_audio=track("mic"),
        system_audio=track("system"),
        screens=sorted(screens, key=lambda item: item.at_ms),
    )


def assemble(
    directory: Path,
    *,
    audio: Path | None,
    screens_dir: Path | None,
    title: str,
    mic_audio: Path | None = None,
) -> Session:
    """Build a session from files you already have.

    For an OBS audio recording plus a folder of screenshots. Screen timestamps
    come from file modification times, measured from the earliest one, which is
    what a screenshot folder actually gives you.
    """
    screens: list[Screen] = []
    if screens_dir is not None:
        images = sorted(
            (path for path in screens_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES),
            key=lambda path: path.stat().st_mtime,
        )
        if images:
            origin = images[0].stat().st_mtime
            screens = [
                Screen(path=path, at_ms=max(0, int((path.stat().st_mtime - origin) * 1000)))
                for path in images
            ]

    return Session(
        directory=directory,
        title=title,
        started_at=None,
        duration_ms=0,
        mic_audio=mic_audio,
        system_audio=audio,
        screens=screens,
    )
