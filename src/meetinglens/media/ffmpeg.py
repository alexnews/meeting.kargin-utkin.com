"""ffmpeg and ffprobe access.

A system ffmpeg is used when present; otherwise the binary bundled inside the
imageio-ffmpeg wheel, so an installed copy of the tool needs no brew or apt.

ffprobe is not bundled anywhere, so probing falls back to parsing what ffmpeg
prints about an input it was asked to do nothing with.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from meetinglens.errors import MediaError

_DURATION_LINE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d)\.(\d+)")
_VIDEO_SIZE = re.compile(r"Video:.*?[,\s](\d{2,5})x(\d{2,5})[,\s]")


@lru_cache(maxsize=1)
def ffmpeg_binary() -> str:
    """System ffmpeg if on PATH, else the one shipped in the wheel."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise MediaError("no ffmpeg found and imageio-ffmpeg is not installed") from exc
    return str(imageio_ffmpeg.get_ffmpeg_exe())


@lru_cache(maxsize=1)
def ffprobe_binary() -> str | None:
    """ffprobe if the system has one. Nothing bundles it."""
    return shutil.which("ffprobe")


@dataclass(frozen=True)
class MediaInfo:
    duration_ms: int
    width: int
    height: int
    has_audio: bool


def _probe_with_ffprobe(path: Path, binary: str) -> MediaInfo | None:
    result = subprocess.run(
        [binary, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError(f"{path.name} has no video stream")
    duration_s = float(payload.get("format", {}).get("duration", 0.0))
    return MediaInfo(
        duration_ms=int(round(duration_s * 1000)),
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def _probe_with_ffmpeg(path: Path) -> MediaInfo:
    result = subprocess.run(
        [ffmpeg_binary(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    text = result.stderr
    duration = _DURATION_LINE.search(text)
    if duration is None:
        raise MediaError(f"could not read a duration from {path.name}")
    hours, minutes, seconds, fraction = duration.groups()
    total_ms = (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1000
        + int(fraction.ljust(3, "0")[:3])
    )
    size = _VIDEO_SIZE.search(text)
    if size is None:
        raise MediaError(f"{path.name} has no video stream")
    return MediaInfo(
        duration_ms=total_ms,
        width=int(size.group(1)),
        height=int(size.group(2)),
        has_audio="Audio:" in text,
    )


def probe(path: Path) -> MediaInfo:
    """Duration, dimensions and whether there is audio."""
    if not path.exists():
        raise MediaError(f"{path} does not exist")
    binary = ffprobe_binary()
    if binary is not None:
        info = _probe_with_ffprobe(path, binary)
        if info is not None:
            return info
    return _probe_with_ffmpeg(path)


def sample_gray_frames(path: Path, *, fps: int, side: int) -> Iterator[np.ndarray]:
    """Decode once, at `fps`, straight to square grayscale frames.

    Frames are streamed and never written to disk. An hour at 1 fps and 128
    pixels a side is about 57 MB through a pipe, against gigabytes of video.
    """
    command = [
        ffmpeg_binary(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-vf",
        f"fps={fps},scale={side}:{side}:flags=area,format=gray",
        "-f",
        "rawvideo",
        "-",
    ]
    frame_bytes = side * side
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(frame_bytes)
            if not chunk:
                break
            if len(chunk) < frame_bytes:
                break  # trailing partial frame at end of stream
            yield np.frombuffer(chunk, dtype=np.uint8).reshape(side, side)
        process.stdout.close()
        if process.wait() != 0:
            stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
            raise MediaError(f"ffmpeg failed reading {path.name}: {stderr.strip()[:400]}")


def extract_still(path: Path, *, at_ms: int, destination: Path, quality: int) -> None:
    """Write one full-resolution frame as WebP.

    ffmpeg produces a PNG and Pillow writes the WebP, rather than asking ffmpeg
    for WebP directly: not every ffmpeg build includes libwebp, and the one
    bundled in the wheel is not guaranteed to.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        intermediate = Path(scratch) / "frame.png"
        command = [
            ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{at_ms / 1000:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            str(intermediate),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not intermediate.exists():
            raise MediaError(
                f"could not extract a frame at {at_ms} ms: {result.stderr.strip()[:400]}"
            )
        with Image.open(intermediate) as still:
            still.convert("RGB").save(destination, "WEBP", quality=quality, method=6)


def extract_audio(path: Path, destination: Path) -> None:
    """Demux to 16 kHz mono WAV, which is what speech models expect."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_binary(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not destination.exists():
        raise MediaError(f"could not extract audio from {path.name}: {result.stderr.strip()[:400]}")
