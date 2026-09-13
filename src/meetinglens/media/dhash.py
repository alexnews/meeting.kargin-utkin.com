"""Difference hash over a grayscale frame.

dHash compares each pixel to its right-hand neighbour on a reduced grid. The
resulting bits survive rescaling and compression but move when the content
moves, and it is cheap enough to run on every sampled frame of an hour of video.

HASH_SIDE is 24 rather than the textbook 8. That is not a preference, it is a
measurement. Presentation slides are dark text on a light ground, and at 8x8
they reduce to a nearly uniform wash: two completely different slides came out
7 bits apart while adding a bullet moved 3. No threshold separates those.

Measured at 24x24, through a real H.264 encode, in bits out of 576:

    static slide, encoder noise and a moving thumbnail   5 to 7
    build step, one bullet appearing                     5 to 8
    build step, two bullets at once                      17
    slide change, same layout as the one before          19
    slide change, different layout                       29 to 44

So the usable window is 9 to 18, and where to sit inside it is decided by an
asymmetry rather than by taste. Splitting too eagerly is recoverable: the
post-OCR superset pass collapses a build that split. Merging two slides is not
recoverable, because the earlier one is gone from the output entirely. Bias
low. See docs/DECISIONS.md 0007 and 0010.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

HASH_SIDE = 24
HASH_BITS = HASH_SIDE * HASH_SIDE
HEX_WIDTH = HASH_BITS // 4

# Mid-window, biased low for the reason above. Tune with
# MEETINGLENS_DHASH_THRESHOLD: lower if slides go missing, higher if one slide
# shows up twice.
DEFAULT_THRESHOLD = 12


def dhash_from_gray(frame: np.ndarray) -> int:
    """Hash one 2-D grayscale frame."""
    if frame.ndim != 2:
        raise ValueError(f"expected a 2-D grayscale frame, got shape {frame.shape}")
    reduced = Image.fromarray(frame.astype(np.uint8), mode="L").resize(
        (HASH_SIDE + 1, HASH_SIDE), Image.Resampling.BOX
    )
    pixels = np.asarray(reduced, dtype=np.int16)
    brighter_than_right_neighbour = pixels[:, 1:] > pixels[:, :-1]
    packed = np.packbits(brighter_than_right_neighbour.flatten())
    return int.from_bytes(packed.tobytes(), "big")


def hamming(left: int, right: int) -> int:
    """Number of differing bits. 0 means identical."""
    return (left ^ right).bit_count()


def to_hex(value: int) -> str:
    """Database representation: fixed-width lowercase hex."""
    return f"{value:0{HEX_WIDTH}x}"


def from_hex(value: str) -> int:
    return int(value, 16)
