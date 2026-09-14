"""Record a meeting without ever writing a video file.

A video of every meeting is hundreds of megabytes an hour and almost all of it
is the same slide held on screen. This records what is actually needed: audio at
speech bitrate, and a screenshot only when the screen changes.

Roughly 34 MB an hour against roughly 800 MB for a screen recording.

Two audio devices are captured separately when both exist. That separation is
what gives speaker attribution with no diarization model: the microphone is you,
the meeting output device is everybody else.
"""

from __future__ import annotations

import json
import re
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import FrameType

from PIL import Image

from meetinglens.errors import MediaError
from meetinglens.media.dhash import dhash_from_gray, hamming, to_hex
from meetinglens.media.ffmpeg import ffmpeg_binary

SCREENCAPTURE = "/usr/sbin/screencapture"
OSASCRIPT = "/usr/bin/osascript"

ACCESSIBILITY_HELP = (
    "macOS will not let this read a window's position until your terminal has\n"
    "Accessibility permission. Open System Settings, Privacy and Security,\n"
    "Accessibility, and switch on your terminal application. Then try again.\n"
    "Alternatively use --display or --region, which need no permission."
)

# Names are matched loosely, best first. A meeting application's own audio
# device carries everybody else's voices; a virtual loopback device does too.
SYSTEM_DEVICE_HINTS = ("teams audio", "blackhole", "loopback", "soundflower", "aggregate")
MIC_DEVICE_HINTS = ("macbook pro microphone", "built-in", "microphone")

_DEVICE_LINE = re.compile(r"\[(\d+)\]\s+(.+?)\s*$")

# Screenshots are downscaled before storing. Retina screens are 3456 wide and
# OCR gains nothing above about 1920.
MAX_STORED_WIDTH = 1920
SAMPLE_SIDE = 128


@dataclass(frozen=True)
class Target:
    """What to photograph. Narrower is better: a full screen capture records
    whatever else you have open, which is how a meeting document ends up
    containing somebody's inbox."""

    app: str | None = None
    display: int | None = None
    region: tuple[int, int, int, int] | None = None

    @property
    def is_whole_screen(self) -> bool:
        return self.app is None and self.display is None and self.region is None

    def describe(self) -> str:
        if self.app:
            return f"the {self.app} window only"
        if self.display is not None:
            return f"display {self.display} only"
        if self.region:
            x, y, width, height = self.region
            return f"the region {width}x{height} at {x},{y}"
        return "THE WHOLE SCREEN, including everything else you have open"


def window_region(app: str) -> tuple[int, int, int, int]:
    """Where an application's front window currently is."""
    script = (
        f'tell application "System Events" to tell process "{app}" '
        "to get {position, size} of front window"
    )
    result = subprocess.run([OSASCRIPT, "-e", script], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = result.stderr.strip()
        if "assistive access" in message or "-1719" in message:
            raise MediaError(ACCESSIBILITY_HELP)
        raise MediaError(f"could not find a window for {app!r}: {message[:200]}")
    numbers = [int(float(part.strip())) for part in result.stdout.strip().split(",")]
    if len(numbers) != 4:
        raise MediaError(f"unexpected window geometry for {app!r}: {result.stdout.strip()}")
    return numbers[0], numbers[1], numbers[2], numbers[3]


def parse_region(value: str) -> tuple[int, int, int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4 or not all(part.lstrip("-").isdigit() for part in parts):
        raise MediaError(f"--region wants x,y,width,height, got {value!r}")
    x, y, width, height = (int(part) for part in parts)
    if width <= 0 or height <= 0:
        raise MediaError("--region width and height must be positive")
    return x, y, width, height


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str


def list_audio_devices() -> list[AudioDevice]:
    """Ask ffmpeg what AVFoundation can see."""
    result = subprocess.run(
        [ffmpeg_binary(), "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True,
        check=False,
    )
    devices: list[AudioDevice] = []
    in_audio = False
    for line in result.stderr.splitlines():
        if "AVFoundation audio devices" in line:
            in_audio = True
            continue
        if "AVFoundation video devices" in line:
            in_audio = False
            continue
        if not in_audio:
            continue
        match = _DEVICE_LINE.search(line)
        if match:
            devices.append(AudioDevice(index=int(match.group(1)), name=match.group(2).strip()))
    return devices


def _pick(devices: list[AudioDevice], hints: tuple[str, ...]) -> AudioDevice | None:
    for hint in hints:
        for device in devices:
            if hint in device.name.casefold():
                return device
    return None


def _start_audio(device: AudioDevice, destination: Path) -> subprocess.Popen[bytes]:
    """Capture one device to mono mp3 at speech bitrate."""
    return subprocess.Popen(
        [
            ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "avfoundation",
            "-i",
            f":{device.index}",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "32k",
            str(destination),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _grab(scratch: Path, target: Target) -> Path | None:
    """One screenshot of whatever the target says. None if it could not be read."""
    destination = scratch / "shot.jpg"
    destination.unlink(missing_ok=True)
    command = [SCREENCAPTURE, "-x", "-t", "jpg"]

    region = target.region
    if target.app is not None:
        try:
            region = window_region(target.app)
        except MediaError:
            # The window moved, closed or is not frontmost. Skip this tick
            # rather than silently falling back to the whole screen.
            return None
    if region is not None:
        x, y, width, height = region
        command += ["-R", f"{x},{y},{width},{height}"]
    elif target.display is not None:
        command += ["-D", str(target.display)]

    command.append(str(destination))
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0 or not destination.exists():
        return None
    return destination


def _store(source: Path, destination: Path, quality: int) -> None:
    """Downscale and write as WebP."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        frame = image.convert("RGB")
        if frame.width > MAX_STORED_WIDTH:
            height = round(frame.height * MAX_STORED_WIDTH / frame.width)
            frame = frame.resize((MAX_STORED_WIDTH, height), Image.Resampling.LANCZOS)
        frame.save(destination, "WEBP", quality=quality, method=6)


def _hash_of(path: Path) -> int:
    with Image.open(path) as image:
        small = image.convert("L").resize((SAMPLE_SIDE, SAMPLE_SIDE), Image.Resampling.BOX)
        import numpy as np

        return dhash_from_gray(np.asarray(small, dtype=np.uint8))


@dataclass
class _Screen:
    """A screen state being held, written once and replaced as it drifts."""

    path: Path
    start_ms: int
    dhash: int


def record(
    session_dir: Path,
    *,
    title: str,
    target: Target | None = None,
    interval_s: float = 2.0,
    threshold: int = 12,
    stability_ms: int = 2000,
    quality: int = 80,
) -> Path:
    """Capture until interrupted. Returns the session directory.

    Only ever holds one scratch screenshot plus the screens actually kept, so
    disk use stays flat no matter how long the meeting runs.
    """
    if not Path(SCREENCAPTURE).exists():
        raise MediaError("screencapture not found; this capture mode is macOS only")

    what = target or Target()
    if what.app is not None:
        window_region(what.app)  # fail now, with help, rather than mid-meeting

    devices = list_audio_devices()
    microphone = _pick(devices, MIC_DEVICE_HINTS)
    system = _pick(devices, SYSTEM_DEVICE_HINTS)
    if microphone is None and system is None:
        raise MediaError("no audio input devices found")

    screens_dir = session_dir / "screens"
    scratch = session_dir / ".scratch"
    screens_dir.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)

    processes: list[subprocess.Popen[bytes]] = []
    tracks: dict[str, str] = {}
    if microphone is not None:
        processes.append(_start_audio(microphone, session_dir / "audio_mic.mp3"))
        tracks["mic"] = microphone.name
        print(f"  you        {microphone.name}")
    if system is not None:
        processes.append(_start_audio(system, session_dir / "audio_system.mp3"))
        tracks["system"] = system.name
        print(f"  others     {system.name}")
    else:
        print("  others     no meeting audio device found, only your microphone is captured")

    stopping = False

    def stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    previous_handler = signal.signal(signal.SIGINT, stop)
    started = time.monotonic()
    kept: list[dict[str, object]] = []
    current: _Screen | None = None
    candidate_hash: int | None = None
    candidate_first_ms = 0
    index = 0

    print(f"  capturing  {what.describe()}")
    print("\nRecording. Press Ctrl+C when the meeting ends.\n")
    try:
        while not stopping:
            loop_started = time.monotonic()
            now_ms = int((loop_started - started) * 1000)
            shot = _grab(scratch, what)
            if shot is not None:
                frame_hash = _hash_of(shot)

                if current is not None and hamming(frame_hash, current.dhash) < threshold:
                    # Same screen, possibly still building. Keep the newer image
                    # and roll the anchor, so what is stored is the finished
                    # state. A bit-identical frame means nothing moved, so there
                    # is nothing to rewrite: a static slide would otherwise be
                    # written to disk every couple of seconds for an hour.
                    if hamming(frame_hash, current.dhash) > 0:
                        _store(shot, current.path, quality)
                        current.dhash = frame_hash
                    candidate_hash = None
                elif candidate_hash is None or hamming(frame_hash, candidate_hash) >= threshold:
                    candidate_hash = frame_hash
                    candidate_first_ms = now_ms
                elif now_ms - candidate_first_ms + int(interval_s * 1000) >= stability_ms:
                    destination = screens_dir / f"{index:04d}.webp"
                    _store(shot, destination, quality)
                    current = _Screen(
                        path=destination, start_ms=candidate_first_ms, dhash=frame_hash
                    )
                    kept.append({"file": destination.name, "atMs": candidate_first_ms})
                    index += 1
                    candidate_hash = None
                    print(f"  screen {index:3d}  at {candidate_first_ms // 1000:5d}s")

            elapsed = time.monotonic() - loop_started
            remaining = interval_s - elapsed
            if remaining > 0:
                time.sleep(remaining)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        for process in processes:
            if process.stdin is not None:
                try:
                    process.stdin.write(b"q")
                    process.stdin.flush()
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
        shutil.rmtree(scratch, ignore_errors=True)

    duration_ms = int((time.monotonic() - started) * 1000)
    (session_dir / "session.json").write_text(
        json.dumps(
            {
                "title": title,
                "startedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
                "durationMs": duration_ms,
                "tracks": tracks,
                "screens": kept,
                "capturing": what.describe(),
                "dhashThreshold": threshold,
                "anchor": to_hex(current.dhash) if current else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return session_dir


def preview(target: Target) -> Path:
    """One screenshot of what `record` would capture, opened for inspection.

    Deliberately separate from recording: no audio, no database, no session.
    Somebody about to point this at a real meeting should be able to see
    precisely what it photographs first.
    """
    if target.app is not None:
        window_region(target.app)  # raises with help if not permitted

    scratch = Path(tempfile.mkdtemp(prefix="meetinglens-preview-"))
    shot = _grab(scratch, target)
    if shot is None:
        shutil.rmtree(scratch, ignore_errors=True)
        raise MediaError("could not take a screenshot of that target")

    destination = scratch / "preview.webp"
    _store(shot, destination, quality=80)
    shot.unlink(missing_ok=True)
    subprocess.run(["open", str(destination)], check=False, capture_output=True)
    return destination
