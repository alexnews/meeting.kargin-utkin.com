"""Build small test recordings at test time.

No media in git. Each test states its recording as a list of scenes and gets a
real encoded mp4 back, so the ffmpeg plumbing is exercised for real rather than
mocked.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from meetinglens.media.ffmpeg import ffmpeg_binary

VIDEO_SIZE = (640, 360)


@dataclass(frozen=True)
class Scene:
    """One image held on screen for a number of whole seconds."""

    image: Image.Image
    seconds: int


def write_video(destination: Path, scenes: list[Scene], *, output_fps: int = 10) -> Path:
    """Encode scenes into an mp4, one PNG per second of screen time."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        frames = Path(scratch)
        index = 0
        for scene in scenes:
            resized = scene.image.convert("RGB").resize(VIDEO_SIZE, Image.Resampling.LANCZOS)
            for _ in range(scene.seconds):
                resized.save(frames / f"{index:05d}.png")
                index += 1
        if index == 0:
            raise ValueError("a test video needs at least one scene")
        command = [
            ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            "1",
            "-i",
            str(frames / "%05d.png"),
            "-vf",
            f"fps={output_fps}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(destination),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"test video encode failed: {result.stderr[-500:]}")
    return destination
