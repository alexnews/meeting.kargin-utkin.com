"""Settings, resolved from the environment with working defaults.

Every value has a default that produces a working system, so there is nothing to
configure before a first run. Overrides come from MEETINGLENS_* environment
variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from meetinglens.errors import ConfigError
from meetinglens.media.dhash import DEFAULT_THRESHOLD

DEFAULT_HOME = Path.home() / ".meetinglens"
DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "MeetingLens"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return Path(raw).expanduser()


@dataclass(frozen=True)
class Settings:
    """Resolved configuration. Immutable; build a new one rather than mutating."""

    home: Path
    output_dir: Path

    # keyframes
    keyframe_fps: int
    dhash_threshold: int
    stability_ms: int
    webp_quality: int

    # post-OCR passes
    ocr_min_chars: int

    # speaker resolution
    self_name: str | None

    @property
    def db_path(self) -> Path:
        return self.home / "meetinglens.db"

    @property
    def storage_dir(self) -> Path:
        return self.home / "storage"

    @classmethod
    def load(cls) -> Settings:
        self_name = os.environ.get("MEETINGLENS_SELF_NAME") or None
        return cls(
            home=_env_path("MEETINGLENS_HOME", DEFAULT_HOME),
            output_dir=_env_path("MEETINGLENS_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
            keyframe_fps=_env_int("MEETINGLENS_KEYFRAME_FPS", 1),
            dhash_threshold=_env_int("MEETINGLENS_DHASH_THRESHOLD", DEFAULT_THRESHOLD),
            stability_ms=_env_int("MEETINGLENS_STABILITY_MS", 2000),
            webp_quality=_env_int("MEETINGLENS_WEBP_QUALITY", 80),
            ocr_min_chars=_env_int("MEETINGLENS_OCR_MIN_CHARS", 20),
            self_name=self_name.strip() if self_name else None,
        )
