"""The keyframe state machine, tested with no video at all.

detect() consumes a sequence of perceptual hashes, so every scenario from the
design is a handwritten list. Hashes are built as runs of low bits, which makes
the hamming distance between h(a) and h(b) exactly abs(a - b) and lets each test
state its intent in the numbers.

frame_index is the LAST frame that matched the keyframe, not the first. That is
what makes an animated build resolve to the finished slide.
"""

from __future__ import annotations

from meetinglens.stages.keyframes import detect

INTERVAL = 1000
THRESHOLD = 8
STABILITY = 2000


def h(bits: int) -> int:
    """A hash with `bits` low bits set. hamming(h(a), h(b)) == abs(a - b)."""
    return (1 << bits) - 1


A, B, C = h(0), h(20), h(40)
NEAR_A = h(3)  # 3 bits from A, inside the threshold, so it is the same screen


def run(hashes: list[int]) -> list[tuple[int, int, int]]:
    """Return (frame_index, start_ms, end_ms) so assertions read clearly."""
    found = detect(
        hashes,
        frame_interval_ms=INTERVAL,
        threshold=THRESHOLD,
        stability_ms=STABILITY,
    )
    return [(k.frame_index, k.start_ms, k.end_ms) for k in found]


def test_no_frames_yields_nothing() -> None:
    assert run([]) == []


def test_a_screen_shown_once_is_not_stable_enough() -> None:
    assert run([A]) == []


def test_one_static_slide_becomes_one_keyframe_spanning_the_whole_video() -> None:
    assert run([A] * 10) == [(9, 0, 10_000)]


def test_two_slides_split_at_the_moment_the_screen_changed() -> None:
    assert run([A] * 5 + [B] * 5) == [(4, 0, 5_000), (9, 5_000, 10_000)]


def test_changes_inside_the_threshold_are_the_same_screen() -> None:
    assert run([A, A, NEAR_A, A, NEAR_A]) == [(4, 0, 5_000)]


def test_a_crossfade_never_commits_its_transitional_frames() -> None:
    # A holds, two distinct in-between frames, then B settles.
    assert run([A, A, A, h(14), h(30), B, B, B]) == [(2, 0, 5_000), (7, 5_000, 8_000)]


def test_an_abrupt_build_commits_only_the_finished_slide() -> None:
    # Each step differs enough to reset the stability window, so nothing
    # intermediate ever survives long enough to commit.
    build = [h(20), h(30), h(40)]
    assert run([A, A, A] + build + [h(52)] * 3) == [(2, 0, 6_000), (8, 6_000, 9_000)]


def test_a_gradual_build_resolves_to_the_completed_slide() -> None:
    """The case that matters: one bullet at a time barely moves the hash.

    Each step is inside the threshold of the one before, so the whole build is
    a single keyframe. Taking the LAST matching frame means the image is the
    finished slide rather than the slide with one bullet on it.
    """
    gradual = [h(20), h(23), h(26), h(26), h(26)]
    assert run([A, A, A] + gradual) == [(2, 0, 3_000), (7, 3_000, 8_000)]


def test_a_popup_that_disappears_leaves_one_keyframe() -> None:
    assert run([A, A, A, B, A, A, A]) == [(6, 0, 7_000)]


def test_constant_change_commits_nothing() -> None:
    # Video playback: every frame differs from the last by more than the threshold.
    assert run([h(i * 10) for i in range(8)]) == []


def test_a_slide_returning_later_is_a_second_keyframe() -> None:
    assert run([A] * 3 + [B] * 3 + [A] * 3) == [
        (2, 0, 3_000),
        (5, 3_000, 6_000),
        (8, 6_000, 9_000),
    ]


def test_stability_window_is_honoured() -> None:
    # B appears for one frame only, a frame short of the window, so it never commits.
    assert run([A, A, A, B, C, C, C]) == [(2, 0, 4_000), (6, 4_000, 7_000)]


def test_a_drifting_slide_does_not_absorb_the_next_one() -> None:
    """Regression: the comparison anchor must follow the slide as it builds.

    A slide drifts from h(0) to h(17) as bullets appear, each step inside the
    threshold. The next slide is h(3): far from where the drifting slide ended
    up, but close to where it started. Anchoring on the committed hash treats it
    as the same screen and loses a slide; anchoring on the most recent frame
    sees the change.
    """
    drift = [h(0), h(0), h(5), h(11), h(17), h(17)]
    following = [h(3)] * 3
    found = run(drift + following)
    assert len(found) == 2, "the second slide was absorbed into the first"
    assert found[1][1] == 6_000
