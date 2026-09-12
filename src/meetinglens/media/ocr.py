"""Text extraction from a keyframe.

RapidOCR runs the PP-OCR models on ONNXRuntime. It is a fraction of the install
weight of paddlepaddle, ships its models inside the wheel so a first run needs
no download, and reads a slide in about a third of a second.

Reading order is reconstructed from the box geometry, because slide structure
carries meaning: a list of deliverables is not the same information as the same
words in arbitrary order.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class OcrResult:
    text: str
    coverage: float
    """Fraction of the frame covered by text boxes. Near zero for a gallery of
    faces, a tenth or more for a slide."""


@lru_cache(maxsize=1)
def _engine() -> Any:
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def _rows(boxes: list[tuple[float, float, float, float, str]]) -> list[str]:
    """Group boxes into visual lines, then order each line left to right."""
    if not boxes:
        return []
    heights = sorted(bottom - top for _, top, _, bottom, _ in boxes)
    typical_height = heights[len(heights) // 2] or 1.0
    tolerance = typical_height * 0.6

    ordered = sorted(boxes, key=lambda b: ((b[1] + b[3]) / 2, b[0]))
    lines: list[list[tuple[float, float, float, float, str]]] = [[ordered[0]]]
    for box in ordered[1:]:
        centre = (box[1] + box[3]) / 2
        previous = lines[-1][-1]
        previous_centre = (previous[1] + previous[3]) / 2
        if abs(centre - previous_centre) <= tolerance:
            lines[-1].append(box)
        else:
            lines.append([box])

    return [" ".join(part[4] for part in sorted(line, key=lambda b: b[0])) for line in lines]


def read_image(path: Path) -> OcrResult:
    """Extract text and how much of the frame it covers."""
    raw, _ = _engine()(str(path))
    if not raw:
        return OcrResult(text="", coverage=0.0)

    with Image.open(path) as image:
        frame_area = float(image.width * image.height) or 1.0

    boxes: list[tuple[float, float, float, float, str]] = []
    covered = 0.0
    for item in raw:
        polygon, text, _score = item[0], str(item[1]), item[2]
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
        left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
        if not text.strip():
            continue
        boxes.append((left, top, right, bottom, text.strip()))
        covered += (right - left) * (bottom - top)

    return OcrResult(text="\n".join(_rows(boxes)), coverage=min(covered / frame_area, 1.0))
