"""dHash behaviour, including the assumption the build-merge fix depends on."""

from __future__ import annotations

import numpy as np
import pytest

from meetinglens.media.dhash import (
    DEFAULT_THRESHOLD,
    HASH_BITS,
    HEX_WIDTH,
    dhash_from_gray,
    from_hex,
    hamming,
    to_hex,
)
from tests.slides import gray_slide, gray_slide_with_noise

ROADMAP = ["Migrate warehouse", "Kill legacy API", "Pricing model", "Hire two engineers"]


def test_the_same_frame_hashes_the_same() -> None:
    frame = gray_slide("Q3 Roadmap", ROADMAP)
    assert dhash_from_gray(frame) == dhash_from_gray(frame.copy())


def test_a_hash_fits_in_its_declared_width() -> None:
    value = dhash_from_gray(gray_slide("Q3 Roadmap", ROADMAP))
    assert 0 <= value < 2**HASH_BITS


def test_hex_round_trips() -> None:
    value = dhash_from_gray(gray_slide("Q3 Roadmap", ROADMAP))
    assert from_hex(to_hex(value)) == value
    assert len(to_hex(value)) == HEX_WIDTH


def test_a_non_2d_frame_is_rejected() -> None:
    with pytest.raises(ValueError, match="2-D grayscale"):
        dhash_from_gray(np.zeros((8, 8, 3), dtype=np.uint8))


def test_one_more_bullet_barely_moves_the_hash() -> None:
    """The assumption behind taking the LAST frame of a keyframe span.

    A bullet appearing changes few pixels, so a build stays one keyframe and the
    last frame of it is the finished slide.
    """
    partial = dhash_from_gray(gray_slide("Q3 Roadmap", ROADMAP[:3]))
    complete = dhash_from_gray(gray_slide("Q3 Roadmap", ROADMAP))
    assert hamming(partial, complete) < DEFAULT_THRESHOLD


def test_a_slide_change_moves_the_hash_much_further_than_a_build_step() -> None:
    """The margin the threshold lives in, asserted as a ratio rather than a number.

    A change that narrows this gap should fail here, whatever the threshold
    happens to be set to at the time.
    """
    build_step = hamming(
        dhash_from_gray(gray_slide("Q3 Roadmap", ROADMAP[:3])),
        dhash_from_gray(gray_slide("Q3 Roadmap", ROADMAP)),
    )
    same_layout_change = hamming(
        dhash_from_gray(gray_slide("Q3 Roadmap", ROADMAP[:2])),
        dhash_from_gray(gray_slide("Revenue", ["Q1 up 12 percent", "Q2 flat"])),
    )
    assert same_layout_change > build_step * 2, (
        f"build step {build_step}, slide change {same_layout_change}: too close to separate"
    )
    assert build_step < DEFAULT_THRESHOLD < same_layout_change


def test_a_different_slide_moves_the_hash_a_lot() -> None:
    roadmap = dhash_from_gray(gray_slide("Q3 Roadmap", ROADMAP))
    revenue = dhash_from_gray(
        gray_slide("Revenue", ["Q1 up 12 percent", "Q2 flat", "Q3 down on churn"])
    )
    assert hamming(roadmap, revenue) >= DEFAULT_THRESHOLD


def test_compression_noise_and_a_moving_thumbnail_do_not_look_like_a_new_slide() -> None:
    """What a real Teams recording adds on top of a static slide.

    Encoder noise plus a participant thumbnail moving in the corner must stay
    well inside the threshold, or every meeting would produce hundreds of
    near-identical keyframes.
    """
    clean = dhash_from_gray(gray_slide("Q3 Roadmap", ROADMAP))
    for seed in range(5):
        noisy = dhash_from_gray(
            gray_slide_with_noise("Q3 Roadmap", ROADMAP, seed=seed, thumbnail_offset=seed * 12)
        )
        assert hamming(clean, noisy) < DEFAULT_THRESHOLD, f"seed {seed} drifted too far"
