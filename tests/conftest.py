"""Shared fixtures. Every test gets its own database and storage under tmp_path."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from meetinglens.config import Settings
from meetinglens.db import open_migrated


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    defaults = Settings.load()
    return Settings(
        home=tmp_path / "home",
        output_dir=tmp_path / "out",
        keyframe_fps=defaults.keyframe_fps,
        dhash_threshold=defaults.dhash_threshold,
        stability_ms=defaults.stability_ms,
        webp_quality=defaults.webp_quality,
        ocr_min_chars=defaults.ocr_min_chars,
        ocr_min_coverage=defaults.ocr_min_coverage,
        self_name=None,
    )


@pytest.fixture
def conn(settings: Settings) -> Iterator[sqlite3.Connection]:
    connection = open_migrated(settings.db_path)
    yield connection
    connection.close()
