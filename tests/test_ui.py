"""The local window, exercised over real HTTP against a server on a real port."""

from __future__ import annotations

import json
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from meetinglens.config import Settings
from meetinglens.ui.finder import find_recordings
from meetinglens.ui.server import Jobs, _Handler
from tests.slides import render_slide
from tests.video import Scene, write_video


@pytest.fixture
def base_url(settings: Settings) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    handler = type("Handler", (_Handler,), {"settings": settings, "jobs": Jobs()})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - loopback only
        return bytes(response.read())


def post(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - loopback
            ok: dict[str, object] = json.loads(response.read())
            return ok
    except urllib.error.HTTPError as refused:
        failed: dict[str, object] = json.loads(refused.read())
        return failed


def test_the_page_loads(base_url: str) -> None:
    page = get(f"{base_url}/").decode()
    assert "<title>MeetingLens</title>" in page
    assert "Nothing is uploaded" in page


def test_the_page_pulls_in_nothing_from_the_internet(base_url: str) -> None:
    """Local-first means the window works with the network off."""
    page = get(f"{base_url}/").decode()
    for marker in ("http://", "https://", "//cdn", "<script src"):
        assert marker not in page.replace("http://127.0.0.1", ""), f"external reference: {marker}"


def test_processing_a_recording_from_the_window(
    base_url: str, settings: Settings, tmp_path: Path
) -> None:
    video = write_video(
        tmp_path / "team sync.mp4",
        [
            Scene(render_slide("Q3 Roadmap", ["Migrate warehouse", "Kill legacy API"]), 4),
            Scene(render_slide("Revenue", ["Q1 up 12 percent", "Q2 flat"]), 4),
        ],
    )
    transcript = tmp_path / "team sync.vtt"
    transcript.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<v Ann Lee>Here is the roadmap.</v>\n",
        encoding="utf-8",
    )

    started = post(
        f"{base_url}/api/process",
        {"video": str(video), "transcript": str(transcript), "title": "Team Sync"},
    )
    job_id = started["id"]

    deadline = time.time() + 120
    job: dict[str, object] = {}
    while time.time() < deadline:
        job = json.loads(get(f"{base_url}/api/jobs/{job_id}"))
        if job["stage"] in ("done", "failed"):
            break
        time.sleep(0.2)

    assert job["stage"] == "done", job.get("error")
    assert job["slides"] == 2
    assert job["turns"] == 1
    assert Path(str(job["markdown"])).exists()

    meetings = json.loads(get(f"{base_url}/api/meetings"))
    assert meetings[0]["title"] == "Team Sync"

    detail = json.loads(get(f"{base_url}/api/meeting/{job['meetingId']}"))
    kinds = [entry["kind"] for entry in detail["entries"]]
    assert "slide" in kinds and "speech" in kinds

    image_url = next(e["image"] for e in detail["entries"] if e["kind"] == "slide")
    assert get(f"{base_url}{image_url}")[:4] == b"RIFF", "a WebP should come back"


def test_a_missing_recording_is_reported_not_crashed(base_url: str) -> None:
    result = post(f"{base_url}/api/process", {"video": "/nope/missing.mp4"})
    assert "error" in result


def test_images_outside_the_storage_directory_are_refused(
    base_url: str, settings: Settings, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """The window must not become a way to read arbitrary files."""
    secret = tmp_path / "private.webp"
    secret.write_bytes(b"RIFFfake")
    conn.execute("INSERT INTO meeting (id, title, source_path) VALUES (1, 'm', '/tmp/a.mp4')")
    cursor = conn.execute(
        "INSERT INTO keyframe (meeting_id, start_ms, end_ms, image_path, dhash)"
        " VALUES (1, 0, 1, ?, '00')",
        (str(secret),),
    )
    conn.commit()

    with pytest.raises(urllib.error.HTTPError) as refused:
        get(f"{base_url}/image/{cursor.lastrowid}")
    assert refused.value.code == 404


def test_the_finder_pairs_a_video_with_its_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    (folder / "weekly sync.mp4").write_bytes(b"x")
    (folder / "weekly sync.vtt").write_text("WEBVTT\n")
    (folder / "no transcript.mp4").write_bytes(b"x")
    monkeypatch.setattr("meetinglens.ui.finder.SEARCH_DIRECTORIES", (folder,))

    found = {item.video.name: item for item in find_recordings()}
    assert found["weekly sync.mp4"].transcript is not None
    assert found["no transcript.mp4"].transcript is None
    assert found["weekly sync.mp4"].title == "weekly sync"
