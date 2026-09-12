#!/usr/bin/env python3
"""Refuse to let recordings or large files into a public repository.

The tool processes meetings that contain other people's confidential material.
A .gitignore is a convention; this is a check that fails the build. It runs in
CI and can be installed as a pre-commit hook.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024

FORBIDDEN_SUFFIXES = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".vtt",
    ".srt",
}

ALLOWED_PATHS = {Path("tests/fixtures/.gitkeep")}


def tracked_files() -> list[Path]:
    output = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    return [Path(name) for name in output.decode().split("\0") if name]


def main() -> int:
    problems: list[str] = []
    for path in tracked_files():
        if path in ALLOWED_PATHS or not path.exists():
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(f"{path}: media and transcripts must never be committed")
            continue
        size = path.stat().st_size
        if size > MAX_BYTES:
            problems.append(f"{path}: {size / 1_048_576:.1f} MB exceeds the 10 MB limit")

    if problems:
        print("Refusing this tree:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "\nTest fixtures are generated at test time. See tests/video.py.",
            file=sys.stderr,
        )
        return 1
    print(f"checked {len(tracked_files())} tracked files: no media, none over 10 MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
