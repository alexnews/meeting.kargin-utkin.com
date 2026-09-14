"""Command line entry point.

Everything here stays thin: argument handling and reporting only, with the work
in meetinglens.stages.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from meetinglens import __version__, capture
from meetinglens import session as session_module
from meetinglens.config import Settings
from meetinglens.db import open_migrated
from meetinglens.errors import MeetingLensError
from meetinglens.session import Session
from meetinglens.stages import export, ingest, keyframes, ocr, screens
from meetinglens.stages import transcript as transcript_stage

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Record a meeting as audio plus screens, and turn it into one markdown file.",
)
db_app = typer.Typer(no_args_is_help=True, help="Database inspection and maintenance.")
app.add_typer(db_app, name="db")

_UNSAFE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    return _UNSAFE.sub("-", value.casefold()).strip("-")[:50] or "meeting"


def _report(result: export.ExportResult, slides: int, turns: int, dropped: int) -> None:
    typer.echo("")
    typer.echo(f"{slides} screens kept, {dropped} dropped, {turns} turns")
    typer.echo(str(result.markdown))


def _process_session(settings: Settings, session: Session, out: Path | None) -> None:
    connection = open_migrated(settings.db_path)
    try:
        meeting_id = ingest.run_session(connection, session)

        typer.echo(f"screens    {len(session.screens)} captured")
        found = screens.run(connection, session, meeting_id)

        tracks = ", ".join(name for name, _ in session.audio_tracks) or "none"
        typer.echo(f"transcript {tracks} ({transcript_stage.model_name()} model)")
        turns = 0
        try:
            turns = transcript_stage.run_session(connection, settings, session, meeting_id)
        except transcript_stage.TranscriptUnavailable as unavailable:
            typer.secho(f"           {unavailable}", fg=typer.colors.YELLOW, err=True)

        typer.echo(f"ocr        reading {found} screens")
        kept = ocr.run(connection, settings, meeting_id)

        typer.echo("export     writing markdown")
        result = export.run(connection, settings, meeting_id, output_dir=out)
        _report(result, kept, turns, found - kept)
    finally:
        connection.close()


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command()
def record(
    title: Annotated[
        str | None, typer.Option("--title", help="Meeting title. Defaults to the date and time.")
    ] = None,
    window: Annotated[
        str | None,
        typer.Option(
            "--app", help='Capture only this app\'s window, e.g. --app "Microsoft Teams".'
        ),
    ] = None,
    display: Annotated[
        int | None,
        typer.Option("--display", help="Capture only this display. 1 is the main one."),
    ] = None,
    region: Annotated[
        str | None,
        typer.Option("--region", help="Capture only this rectangle: x,y,width,height."),
    ] = None,
    whole_screen: Annotated[
        bool,
        typer.Option("--whole-screen", help="Capture everything on screen. Records what is open."),
    ] = False,
    every: Annotated[float, typer.Option("--every", help="Seconds between screen checks.")] = 2.0,
    out: Annotated[
        Path | None, typer.Option("--out", file_okay=False, help="Where to write the document.")
    ] = None,
) -> None:
    """Record the meeting, then turn it into a document.

    Captures audio and a screenshot only when the screen changes. No video file
    is ever written, so an hour costs tens of megabytes rather than hundreds.
    """
    settings = Settings.load()
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    name = title or f"Meeting {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    directory = settings.home / "recordings" / f"{stamp}-{_slug(name)}"

    try:
        target = capture.Target(
            app=window,
            display=display,
            region=capture.parse_region(region) if region else None,
        )
        if target.is_whole_screen and not whole_screen:
            typer.secho(
                "\nThis would photograph your entire screen every few seconds.\n"
                "Anything open goes into the document: messages, mail, other tabs.\n",
                fg=typer.colors.YELLOW,
            )
            typer.echo('Better: --app "Microsoft Teams", or --display 2, or --region x,y,w,h.\n')
            if not sys.stdin.isatty():
                typer.secho("Pass --whole-screen if you really mean it.", fg=typer.colors.RED)
                raise typer.Exit(code=2)
            if not typer.confirm("Record the whole screen anyway?", default=False):
                raise typer.Exit(code=1)

        typer.echo("Audio devices:")
        capture.record(
            directory,
            title=name,
            target=target,
            interval_s=every,
            threshold=settings.dhash_threshold,
            stability_ms=settings.stability_ms,
            quality=settings.webp_quality,
        )
        typer.echo("\nRecording stopped. Processing.\n")
        _process_session(settings, session_module.load(directory), out)
    except MeetingLensError as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error


@app.command()
def process(
    path: Annotated[
        Path | None,
        typer.Argument(exists=True, help="A recording session directory, or a video file."),
    ] = None,
    audio: Annotated[
        Path | None,
        typer.Option(
            "--audio",
            exists=True,
            dir_okay=False,
            help="An audio recording, for example from OBS.",
        ),
    ] = None,
    screens_dir: Annotated[
        Path | None,
        typer.Option("--screens", exists=True, file_okay=False, help="A folder of screenshots."),
    ] = None,
    transcript: Annotated[
        Path | None,
        typer.Option("--transcript", "-t", exists=True, dir_okay=False, help="A .vtt transcript."),
    ] = None,
    title: Annotated[str | None, typer.Option("--title", help="Meeting title.")] = None,
    out: Annotated[
        Path | None, typer.Option("--out", file_okay=False, help="Where to write.")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Redo every stage.")] = False,
) -> None:
    """Turn a recording into a document.

    Give it a session directory from `record`, or your own audio recording and
    folder of screenshots, or a video file.
    """
    settings = Settings.load()

    if audio is not None or screens_dir is not None:
        name = title or (audio.stem if audio else "Meeting")
        _process_session(
            settings,
            session_module.assemble(
                (screens_dir or audio.parent if audio else Path.cwd()),
                audio=audio,
                screens_dir=screens_dir,
                title=name,
            ),
            out,
        )
        return

    if path is None:
        typer.secho(
            "Give me something to process: a session directory, a video file,\n"
            "or --audio with --screens.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    if session_module.is_session(path):
        _process_session(settings, session_module.load(path), out)
        return

    connection = open_migrated(settings.db_path)
    try:
        typer.echo(f"reading    {path.name}")
        meeting_id = ingest.run(connection, path, transcript=transcript, title=title)

        typer.echo("keyframes  detecting screen changes")
        found = keyframes.run(connection, settings, meeting_id, force=force)

        source = transcript.name if transcript else "no transcript, transcribing locally"
        typer.echo(f"transcript {source}")
        turns = 0
        try:
            turns = transcript_stage.run(connection, settings, meeting_id, force=force)
        except transcript_stage.TranscriptUnavailable as unavailable:
            typer.secho(f"           {unavailable}", fg=typer.colors.YELLOW, err=True)

        typer.echo(f"ocr        reading {found} keyframes")
        kept = ocr.run(connection, settings, meeting_id, force=force)

        typer.echo("export     writing markdown")
        result = export.run(connection, settings, meeting_id, output_dir=out)
        _report(result, kept, turns, found - kept)
    except MeetingLensError as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error
    finally:
        connection.close()


@app.command()
def preview(
    window: Annotated[
        str | None,
        typer.Option("--app", help='Preview this app\'s window, e.g. --app "Microsoft Teams".'),
    ] = None,
    display: Annotated[
        int | None, typer.Option("--display", help="Preview this display. 1 is the main one.")
    ] = None,
    region: Annotated[
        str | None, typer.Option("--region", help="Preview this rectangle: x,y,width,height.")
    ] = None,
) -> None:
    """Take one screenshot of what recording would capture, and open it.

    Records nothing, saves nothing to the database, captures no audio. Use it
    to check exactly what would end up in a document before you trust it with a
    real meeting.
    """
    try:
        target = capture.Target(
            app=window,
            display=display,
            region=capture.parse_region(region) if region else None,
        )
        destination = capture.preview(target)
    except MeetingLensError as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"This is what would be recorded: {target.describe()}")
    typer.echo(str(destination))
    typer.echo("\nDelete it when you have looked: rm " + str(destination))


@app.command()
def devices() -> None:
    """List the audio devices capture can use."""
    for device in capture.list_audio_devices():
        typer.echo(f"[{device.index}] {device.name}")


@app.command()
def ui(
    port: Annotated[int, typer.Option("--port", help="Local port to listen on.")] = 8765,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Do not open a browser window.")
    ] = False,
) -> None:
    """Open the MeetingLens window."""
    from meetinglens.ui import serve

    serve(Settings.load(), port=port, open_browser=not no_browser)


@db_app.command("path")
def db_path() -> None:
    """Print the database file location."""
    typer.echo(str(Settings.load().db_path))


@db_app.command("migrate")
def db_migrate() -> None:
    """Create or update the database schema."""
    settings = Settings.load()
    connection = open_migrated(settings.db_path)
    connection.close()
    typer.echo(f"schema up to date at {settings.db_path}")
