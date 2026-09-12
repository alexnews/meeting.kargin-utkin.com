"""Parsing Teams transcripts.

Teams is not consistent across tenants: some write a GUID cue identifier, some
omit hours from timestamps, some use a voice span and some a bare name prefix.
All of it has to parse without configuration.
"""

from __future__ import annotations

from meetinglens.vtt import Cue, merge_adjacent, parse_vtt

TEAMS_TYPICAL = """WEBVTT

d1b1a8e0-0000-0000-0000-000000000001/1-0
00:00:03.120 --> 00:00:07.440
<v Alex Kargin>So let us start with the roadmap.</v>

d1b1a8e0-0000-0000-0000-000000000001/2-0
00:00:07.900 --> 00:00:11.020
<v Sarah Chen>These are the priorities for the quarter.</v>
"""


def test_a_typical_teams_transcript() -> None:
    cues = parse_vtt(TEAMS_TYPICAL)
    assert cues == [
        Cue(3120, 7440, "Alex Kargin", "So let us start with the roadmap."),
        Cue(7900, 11020, "Sarah Chen", "These are the priorities for the quarter."),
    ]


def test_hours_may_be_omitted() -> None:
    cues = parse_vtt("WEBVTT\n\n01:02.500 --> 01:05.000\n<v Ann Lee>Short form.</v>\n")
    assert cues[0].start_ms == 62_500
    assert cues[0].end_ms == 65_000


def test_an_hour_long_meeting_keeps_its_hours() -> None:
    cues = parse_vtt("WEBVTT\n\n01:02:03.400 --> 01:02:05.000\n<v Ann Lee>Late on.</v>\n")
    assert cues[0].start_ms == 3_723_400


def test_voice_tags_may_carry_classes() -> None:
    cues = parse_vtt("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v.loud Ann Lee>Loud.</v>\n")
    assert cues[0].speaker == "Ann Lee"
    assert cues[0].text == "Loud."


def test_a_bare_name_prefix_counts_when_it_recurs() -> None:
    content = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.000\nAnn Lee: First thing.\n\n"
        "00:00:03.000 --> 00:00:04.000\nAnn Lee: Second thing.\n"
    )
    cues = parse_vtt(content)
    assert [c.speaker for c in cues] == ["Ann Lee", "Ann Lee"]
    assert cues[0].text == "First thing."


def test_a_one_off_colon_is_not_a_speaker() -> None:
    """Otherwise 'Note:' or 'Warning:' would invent a participant."""
    content = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.000\nNote: the deadline moved.\n\n"
        "00:00:03.000 --> 00:00:04.000\n<v Ann Lee>Understood.</v>\n"
    )
    cues = parse_vtt(content)
    assert cues[0].speaker is None
    assert cues[0].text == "Note: the deadline moved."
    assert cues[1].speaker == "Ann Lee"


def test_multi_line_cues_join_into_one_utterance() -> None:
    content = "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\n<v Ann Lee>One line\nand another.</v>\n"
    assert parse_vtt(content)[0].text == "One line and another."


def test_note_and_style_blocks_are_ignored() -> None:
    content = (
        "WEBVTT\n\nNOTE this file was produced by a robot\n\n"
        "STYLE\n::cue { color: white }\n\n"
        "00:00:01.000 --> 00:00:02.000\n<v Ann Lee>Only cue.</v>\n"
    )
    cues = parse_vtt(content)
    assert len(cues) == 1
    assert cues[0].text == "Only cue."


def test_markup_inside_the_text_is_stripped() -> None:
    content = (
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
        "<v Ann Lee><c.colorE5E5E5>Emphasis</c> <i>here</i>.</v>\n"
    )
    assert parse_vtt(content)[0].text == "Emphasis here."


def test_windows_line_endings_and_a_byte_order_mark() -> None:
    content = "﻿WEBVTT\r\n\r\n00:00:01.000 --> 00:00:02.000\r\n<v Ann Lee>Fine.</v>\r\n"
    assert parse_vtt(content)[0].text == "Fine."


def test_an_empty_transcript_is_not_an_error() -> None:
    assert parse_vtt("WEBVTT\n") == []


def test_cues_with_no_text_are_dropped() -> None:
    content = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v Ann Lee></v>\n"
    assert parse_vtt(content) == []


def test_adjacent_cues_from_one_speaker_merge_into_a_paragraph() -> None:
    cues = [
        Cue(0, 2000, "Ann Lee", "First part"),
        Cue(2300, 4000, "Ann Lee", "and the rest."),
        Cue(4200, 6000, "Bob Ray", "My turn."),
    ]
    merged = merge_adjacent(cues, max_gap_ms=2000)
    assert merged == [
        Cue(0, 4000, "Ann Lee", "First part and the rest."),
        Cue(4200, 6000, "Bob Ray", "My turn."),
    ]


def test_a_long_pause_starts_a_new_utterance() -> None:
    cues = [Cue(0, 2000, "Ann Lee", "Before."), Cue(9000, 10_000, "Ann Lee", "After.")]
    assert merge_adjacent(cues, max_gap_ms=2000) == cues
