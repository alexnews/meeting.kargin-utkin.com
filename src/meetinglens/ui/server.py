"""A local window for MeetingLens.

Standard library only, on purpose: this is a local-first tool and adding a web
framework to show one page would be the largest dependency in the project.

Binds to the loopback interface only. Nothing is exposed to the network, and
nothing leaves the machine.
"""

from __future__ import annotations

import json
import mimetypes
import subprocess
import threading
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from meetinglens import __version__
from meetinglens.align import Slide, Speech, timeline
from meetinglens.config import Settings
from meetinglens.db import open_migrated
from meetinglens.errors import MeetingLensError
from meetinglens.stages import export, ingest, keyframes, ocr
from meetinglens.stages import transcript as transcript_stage
from meetinglens.ui.finder import find_recordings

STAGE_LABELS = {
    "reading": "Reading the recording",
    "keyframes": "Finding slides",
    "transcript": "Reading the transcript",
    "ocr": "Extracting slide text",
    "export": "Writing the document",
    "done": "Done",
    "failed": "Failed",
}


@dataclass
class Job:
    id: str
    title: str
    stage: str = "reading"
    error: str | None = None
    meeting_id: int | None = None
    slides: int = 0
    turns: int = 0
    folder: str | None = None
    markdown: str | None = None
    warning: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "stage": self.stage,
            "label": STAGE_LABELS.get(self.stage, self.stage),
            "error": self.error,
            "warning": self.warning,
            "meetingId": self.meeting_id,
            "slides": self.slides,
            "turns": self.turns,
            "folder": self.folder,
            "markdown": self.markdown,
        }


@dataclass
class Jobs:
    """Background work, keyed by id. One meeting at a time is plenty."""

    items: dict[str, Job] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def create(self, title: str) -> Job:
        with self.lock:
            job = Job(id=f"job{len(self.items) + 1}", title=title)
            self.items[job.id] = job
            return job

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return self.items.get(job_id)


def _run_pipeline(job: Job, settings: Settings, video: Path, transcript: Path | None) -> None:
    """The whole pipeline, on a worker thread, updating the job as it goes."""
    connection = open_migrated(settings.db_path)
    try:
        job.stage = "reading"
        meeting_id = ingest.run(connection, video, transcript=transcript, title=job.title)
        job.meeting_id = meeting_id

        job.stage = "keyframes"
        keyframes.run(connection, settings, meeting_id)

        job.stage = "transcript"
        try:
            job.turns = transcript_stage.run(connection, settings, meeting_id)
        except transcript_stage.TranscriptUnavailable as unavailable:
            job.warning = str(unavailable).replace("\n           ", " ")
            job.turns = 0

        job.stage = "ocr"
        job.slides = ocr.run(connection, settings, meeting_id)

        job.stage = "export"
        result = export.run(connection, settings, meeting_id)
        job.folder = str(result.directory)
        job.markdown = str(result.markdown)
        job.slides = result.slides
        job.stage = "done"
    except MeetingLensError as error:
        job.error = str(error)
        job.stage = "failed"
    except Exception as error:  # noqa: BLE001 - the window must show any failure
        job.error = f"{type(error).__name__}: {error}"
        job.stage = "failed"
    finally:
        connection.close()


def _meeting_summaries(settings: Settings) -> list[dict[str, Any]]:
    connection = open_migrated(settings.db_path)
    try:
        rows = connection.execute(
            "SELECT m.id, m.title, m.started_at, m.duration_ms, m.status,"
            "  (SELECT count(*) FROM keyframe k WHERE k.meeting_id = m.id AND k.dropped = 0)"
            "    AS slides,"
            "  (SELECT count(*) FROM utterance u WHERE u.meeting_id = m.id) AS turns"
            " FROM meeting m ORDER BY m.id DESC LIMIT 50"
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "title": str(row["title"]),
                "startedAt": row["started_at"],
                "durationMs": row["duration_ms"],
                "status": row["status"],
                "slides": int(row["slides"]),
                "turns": int(row["turns"]),
            }
            for row in rows
        ]
    finally:
        connection.close()


def _meeting_detail(settings: Settings, meeting_id: int) -> dict[str, Any]:
    connection = open_migrated(settings.db_path)
    try:
        meeting = connection.execute(
            "SELECT title, started_at, duration_ms FROM meeting WHERE id = ?", (meeting_id,)
        ).fetchone()
        if meeting is None:
            return {}
        entries: list[dict[str, Any]] = []
        for entry in timeline(connection, meeting_id):
            if isinstance(entry, Slide):
                entries.append(
                    {
                        "kind": "slide",
                        "atMs": entry.at_ms,
                        "text": entry.text,
                        "image": f"/image/{entry.keyframe_id}",
                    }
                )
            elif isinstance(entry, Speech):
                entries.append(
                    {
                        "kind": "speech",
                        "atMs": entry.at_ms,
                        "speaker": entry.speaker,
                        "isSelf": entry.is_self,
                        "text": entry.text,
                    }
                )
        return {
            "title": str(meeting["title"]),
            "startedAt": meeting["started_at"],
            "durationMs": meeting["duration_ms"],
            "entries": entries,
        }
    finally:
        connection.close()


def _keyframe_path(settings: Settings, keyframe_id: int) -> Path | None:
    connection = open_migrated(settings.db_path)
    try:
        row = connection.execute(
            "SELECT image_path FROM keyframe WHERE id = ?", (keyframe_id,)
        ).fetchone()
        if row is None:
            return None
        path = Path(str(row["image_path"]))
        # Only ever serve from inside our own storage directory.
        try:
            path.resolve().relative_to(settings.storage_dir.resolve())
        except ValueError:
            return None
        return path if path.exists() else None
    finally:
        connection.close()


def _reveal(path: Path) -> None:
    """Show a folder in Finder. Best effort; a failure is not worth reporting."""
    try:
        subprocess.run(["open", str(path)], check=False, capture_output=True)
    except OSError:
        pass


class _Handler(BaseHTTPRequestHandler):
    settings: Settings
    jobs: Jobs

    server_version = f"MeetingLens/{__version__}"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Quiet. The window is the interface, not the terminal."""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        route = urlparse(self.path).path

        if route in ("/", "/index.html"):
            page = resources.files("meetinglens.ui").joinpath("page.html").read_bytes()
            self._send(200, page, "text/html; charset=utf-8")
            return

        if route == "/api/recordings":
            self._json(
                [
                    {
                        "key": item.key,
                        "title": item.title,
                        "video": str(item.video),
                        "folder": str(item.video.parent),
                        "name": item.video.name,
                        "transcript": str(item.transcript) if item.transcript else None,
                        "transcriptName": item.transcript.name if item.transcript else None,
                        "sizeMb": round(item.size_bytes / 1_048_576, 1),
                    }
                    for item in find_recordings()
                ]
            )
            return

        if route == "/api/meetings":
            self._json(_meeting_summaries(self.settings))
            return

        if route.startswith("/api/jobs/"):
            job = self.jobs.get(route.rsplit("/", 1)[-1])
            self._json(job.as_dict() if job else {"error": "no such job"}, 200 if job else 404)
            return

        if route.startswith("/api/meeting/"):
            try:
                meeting_id = int(route.rsplit("/", 1)[-1])
            except ValueError:
                self._json({"error": "bad id"}, 400)
                return
            self._json(_meeting_detail(self.settings, meeting_id))
            return

        if route.startswith("/image/"):
            try:
                keyframe_id = int(route.rsplit("/", 1)[-1])
            except ValueError:
                self._send(400, b"bad id", "text/plain")
                return
            path = _keyframe_path(self.settings, keyframe_id)
            if path is None:
                self._send(404, b"not found", "text/plain")
                return
            kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self._send(200, path.read_bytes(), kind)
            return

        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        route = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "bad request"}, 400)
            return

        if route == "/api/process":
            video = Path(unquote(str(payload.get("video", ""))))
            if not video.is_file():
                self._json({"error": "that recording is no longer there"}, 400)
                return
            raw_transcript = payload.get("transcript")
            transcript = Path(unquote(str(raw_transcript))) if raw_transcript else None
            if transcript is not None and not transcript.is_file():
                transcript = None

            title = str(payload.get("title") or video.stem)
            job = self.jobs.create(title)
            threading.Thread(
                target=_run_pipeline,
                args=(job, self.settings, video, transcript),
                daemon=True,
            ).start()
            self._json(job.as_dict())
            return

        if route == "/api/reveal":
            folder = Path(str(payload.get("folder", "")))
            if folder.exists():
                _reveal(folder)
                self._json({"ok": True})
                return
            self._json({"error": "not found"}, 404)
            return

        self._json({"error": "not found"}, 404)


def serve(settings: Settings, *, port: int = 8765, open_browser: bool = True) -> None:
    """Run the window until interrupted."""
    handler = type("Handler", (_Handler,), {"settings": settings, "jobs": Jobs()})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"MeetingLens is open at {url}")
    print("Leave this running. Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
