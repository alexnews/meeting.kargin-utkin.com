"""Difference hash over a grayscale frame.

dHash compares each pixel to its right-hand neighbour on a reduced grid. The
resulting bits survive rescaling and compression but move when the content
moves, and it is cheap enough to run on every sampled frame of an hour of video.

HASH_SIDE is 24 rather than the textbook 8. That is not a preference, it is a
measurement. Presentation slides are dark text on a light ground, and at 8x8
they reduce to a nearly uniform wash: two completely different slides came out
7 bits apart while adding a bullet to a slide moved 3 bits. No threshold
separates those. At 24x24 the same pair are 38 bits apart against 12 for the
build step, which leaves a wide window. See docs/DECISIONS.md 0005.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

HASH_SIDE = 24
HASH_BITS = HASH_SIDE * HASH_SIDE
HEX_WIDTH = HASH_BITS // 4

# Roughly 4% of the bits: above the drift of an animated build, well below a
# genuine slide change. Tune with MEETINGLENS_DHASH_THRESHOLD.
DEFAULT_THRESHOLD = 24


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
