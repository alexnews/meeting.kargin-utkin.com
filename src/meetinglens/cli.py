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
) -> None:
    """Process a recording into a markdown file."""
    settings = Settings.load()
    try:
        conn = open_migrated(settings.db_path)
    except MeetingLensError as exc:
        raise typer.Exit(code=1) from exc
    conn.close()
    typer.echo(
        f"not yet implemented: process {video.name}"
        f"{' with ' + transcript.name if transcript else ''}"
        f"{' titled ' + title if title else ''}"
    )
    raise typer.Exit(code=2)


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
