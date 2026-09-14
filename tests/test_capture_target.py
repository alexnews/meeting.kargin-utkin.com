"""What the recorder is allowed to photograph.

A meeting recorder that quietly captures the whole screen puts messages, mail
and everything else into the document. These tests pin the narrowing options and
the fact that whole-screen is never the silent default.
"""

from __future__ import annotations

import pytest

from meetinglens.capture import Target, parse_region
from meetinglens.errors import MediaError


def test_a_region_parses() -> None:
    assert parse_region("0,0,1920,1080") == (0, 0, 1920, 1080)
    assert parse_region(" 100 , 50 , 800 , 600 ") == (100, 50, 800, 600)


@pytest.mark.parametrize("bad", ["1,2,3", "a,b,c,d", "0,0,0,100", "0,0,100,-5", ""])
def test_a_malformed_region_is_rejected(bad: str) -> None:
    with pytest.raises(MediaError):
        parse_region(bad)


def test_only_an_unset_target_counts_as_the_whole_screen() -> None:
    assert Target().is_whole_screen
    assert not Target(app="Microsoft Teams").is_whole_screen
    assert not Target(display=2).is_whole_screen
    assert not Target(region=(0, 0, 100, 100)).is_whole_screen


def test_the_whole_screen_description_says_what_it_means() -> None:
    """It appears in the terminal and in session.json, so it has to be blunt."""
    described = Target().describe()
    assert "WHOLE SCREEN" in described
    assert "everything else you have open" in described


def test_a_narrowed_target_describes_itself_precisely() -> None:
    assert Target(app="Microsoft Teams").describe() == "the Microsoft Teams window only"
    assert Target(display=2).describe() == "display 2 only"
    assert Target(region=(10, 20, 800, 600)).describe() == "the region 800x600 at 10,20"
