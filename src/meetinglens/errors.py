"""Exception types. Everything the CLI catches derives from MeetingLensError."""

from __future__ import annotations


class MeetingLensError(Exception):
    """Base for every error this tool raises deliberately."""


class ConfigError(MeetingLensError):
    """A setting is missing or malformed."""


class MediaError(MeetingLensError):
    """ffmpeg or ffprobe failed, or the input file is not usable."""


class StageError(MeetingLensError):
    """A pipeline stage could not complete."""
