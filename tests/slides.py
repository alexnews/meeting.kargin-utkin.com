"""Render slide images for tests, and reduce them the way the pipeline does.

No media files in git. Every fixture is drawn at test time, which keeps the
repository small and makes each scenario readable as code.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FULL_SIZE = (1280, 720)
SAMPLE_SIZE = (128, 128)


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def render_slide(title: str, bullets: list[str]) -> Image.Image:
    """A plain light slide: a title and a numbered list, as a presentation deck."""
    image = Image.new("RGB", FULL_SIZE, (245, 245, 245))
    draw = ImageDraw.Draw(image)
    draw.text((80, 70), title, fill=(20, 20, 20), font=_font(56))
    for row, text in enumerate(bullets):
        draw.text((110, 200 + row * 70), f"{row + 1}. {text}", fill=(40, 40, 40), font=_font(40))
    return image


def as_sampled_gray(image: Image.Image) -> np.ndarray:
    """What the decoder hands the hasher: 128x128 grayscale."""
    reduced = image.convert("L").resize(SAMPLE_SIZE, Image.Resampling.BOX)
    return np.asarray(reduced, dtype=np.uint8)


def gray_slide(title: str, bullets: list[str]) -> np.ndarray:
    return as_sampled_gray(render_slide(title, bullets))


def gray_slide_with_noise(
    title: str, bullets: list[str], *, seed: int, thumbnail_offset: int
) -> np.ndarray:
    """The same slide as a real recording would deliver it.

    Adds encoder-style noise and a participant thumbnail that moves between
    frames, which is what Teams composites over shared content.
    """
    image = render_slide(title, bullets)
    draw = ImageDraw.Draw(image)
    top = 480 + (thumbnail_offset % 40)
    draw.rectangle([(1050, top), (1230, top + 130)], fill=(90, 90, 110))
    draw.text((1070, top + 100), "Sarah C.", fill=(235, 235, 235), font=_font(22))

    rng = np.random.default_rng(seed)
    pixels = np.asarray(image, dtype=np.int16)
    noise = rng.integers(-6, 7, size=pixels.shape, dtype=np.int16)
    noisy = Image.fromarray(np.clip(pixels + noise, 0, 255).astype(np.uint8), mode="RGB")
    return as_sampled_gray(noisy)
