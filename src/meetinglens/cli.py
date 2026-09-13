"""Command line entry point.

Commands grow as stages land. Everything here stays thin: argument handling and
reporting only, with the work in meetinglens.stages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from meetinglens import __version__
from meetinglens.config import Settings
from meetinglens.db import open_migrated
from meetinglens.errors import MeetingLensError
from meetinglens.stages import export, ingest, keyframes, ocr
from meetinglens.stages import transcript as transcript_stage

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Turn a Teams meeting recording into one markdown file.",
)
db_app = typer.Typer(no_args_is_help=True, help="Database inspection and maintenance.")
app.add_typer(db_app, name="db")


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command()
def process(
    video: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, help="Teams recording, an .mp4 file."),
    ],
    transcript: Annotated[
        Path | None,
        typer.Option(
            "--transcript",
            "-t",
            exists=True,
            dir_okay=False,
            help="Teams transcript .vtt. Without it, audio is transcribed locally.",
        ),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Meeting title. Defaults to the filename."),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            file_okay=False,
            help="Where to write. Defaults to the configured output directory.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Redo every stage instead of reusing finished ones."),
    ] = False,
) -> None:
    """Process a recording into a markdown file."""
    settings = Settings.load()
    try:
        conn = open_migrated(settings.db_path)

        typer.echo(f"reading    {video.name}")
        meeting_id = ingest.run(conn, video, transcript=transcript, title=title)

        typer.echo("keyframes  detecting screen changes")
        found = keyframes.run(conn, settings, meeting_id, force=force)

        source = transcript.name if transcript else "no transcript, transcribing locally"
        typer.echo(f"transcript {source}")
        try:
            turns = transcript_stage.run(conn, settings, meeting_id, force=force)
        except transcript_stage.TranscriptUnavailable as unavailable:
            typer.secho(f"           {unavailable}", fg=typer.colors.YELLOW, err=True)
            turns = 0

        typer.echo(f"ocr        reading {found} keyframes")
        kept = ocr.run(conn, settings, meeting_id, force=force)

        typer.echo("export     writing markdown")
        result = export.run(conn, settings, meeting_id, output_dir=out)
        conn.close()
    except MeetingLensError as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    dropped = found - kept
    typer.echo("")
    typer.echo(f"{kept} slides kept, {dropped} dropped, {turns} turns")
    typer.echo(str(result.markdown))


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
    conn = open_migrated(settings.db_path)
    conn.close()
    typer.echo(f"schema up to date at {settings.db_path}")
