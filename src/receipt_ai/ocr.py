"""OCR engines behind one interface: image path in, ordered text lines out.

Every engine returns list[str] in reading order (top-to-bottom, left-to-right),
because that is the shape the LLM extraction step consumes.
Engines are built lazily so importing this module stays cheap.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


@dataclass
class Box:
    text: str
    x: float  # left edge
    y: float  # vertical centre
    h: float  # text height
    w: float = 0.0  # width
    slope: float = 0.0  # dy/dx of the box's top/bottom edges (tilt of the photo here)

    @classmethod
    def from_quad(cls, text: str, quad) -> "Box":
        """From 4 corners in detector order: top-left, top-right, bottom-right, bottom-left."""
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = [(float(p[0]), float(p[1])) for p in quad]
        xs = (x0, x1, x2, x3)
        dx = ((x1 - x0) + (x2 - x3)) / 2
        slope = ((y1 - y0) + (y2 - y3)) / 2 / dx if dx > 0 else 0.0
        # Real text height from the left and right edges. The polygon's vertical extent
        # would also include the tilt across the box's width.
        h = ((y3 - y0) + (y2 - y1)) / 2
        return cls(text, min(xs), (y0 + y1 + y2 + y3) / 4, h, max(xs) - min(xs), slope)


MAX_SKEW = 0.15  # ~8.5 degrees; beyond that, box angles are noise, not page tilt


def estimate_skew(boxes: list[Box]) -> float:
    """The photo's tilt as dy/dx: width-weighted median of the boxes' edge slopes.

    Only boxes at least twice as wide as tall vote (a short box's angle is noisy),
    and the median ignores the odd mis-detected box.
    """
    votes = sorted((b.slope, b.w) for b in boxes if b.w >= 2 * b.h > 0)
    if not votes:
        return 0.0
    half, acc = sum(w for _, w in votes) / 2, 0.0
    for slope, w in votes:
        acc += w
        if acc >= half:
            return max(-MAX_SKEW, min(MAX_SKEW, slope))
    return 0.0


def group_lines(boxes: list[Box], deskew: bool = True) -> list[str]:
    """Merge word/segment boxes into printed lines.

    Detectors like PaddleOCR return segments, not lines: "TOTAL" and "31.000" on a
    receipt are often separate boxes far apart horizontally. Two boxes belong to the
    same line when their vertical centres are within half a box height.

    Photos are rarely straight. Tilted ~2.7 degrees (CORD 095), an amount 550 px to the
    right of its label sits 27 px higher, more than half a line, so "TOTAL" and
    "56,181" landed on different lines. Comparing heights *after* undoing the page's
    tilt (y - skew * x) puts them back together.
    """
    skew = estimate_skew(boxes) if deskew else 0.0

    def level(b: Box) -> float:
        return b.y - skew * (b.x + b.w / 2)

    lines: list[list[Box]] = []
    for b in sorted(boxes, key=level):
        if lines:
            ref = lines[-1]
            ref_y = sum(level(r) for r in ref) / len(ref)
            ref_h = sum(r.h for r in ref) / len(ref)
            if abs(level(b) - ref_y) < 0.5 * max(ref_h, b.h):
                ref.append(b)
                continue
        lines.append([b])
    return [" ".join(b.text for b in sorted(line, key=lambda b: b.x)) for line in lines]


def preprocess(path: str | Path) -> np.ndarray:
    """Grayscale, upscale small images, and remove uneven lighting.

    Receipts are often photographed small and with shadows. Tesseract in particular
    expects dark text on an even, light background at roughly 30px character height.
    """
    img = cv2.imread(str(path))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if gray.shape[1] < 1000:
        scale = 1000 / gray.shape[1]
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    # Divide by a heavily blurred copy -> flattens shadows / gradients.
    background = cv2.GaussianBlur(gray, (0, 0), sigmaX=25)
    flat = cv2.divide(gray, background, scale=255)
    return flat


def lines_from_quads(quads: list[tuple[str, list]]) -> list[str]:
    return group_lines([Box.from_quad(text, quad) for text, quad in quads])


def _with_quads(quads: Callable[[str], list]) -> Callable[[str], list[str]]:
    """An engine: path -> lines. It also exposes .quads (path -> raw detector boxes) so
    scripts/cache_ocr.py can store the boxes and re-group them later without re-running OCR."""

    def run(path: str) -> list[str]:
        return lines_from_quads(quads(path))

    run.quads = quads
    return run


def _tesseract(pre: bool) -> Callable[[str], list[str]]:
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE

    def run(path: str) -> list[str]:
        img = preprocess(path) if pre else cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)
        # psm 4: "single column of text of variable sizes" — matches a receipt layout.
        text = pytesseract.image_to_string(img, config="--psm 4")
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    return run


def _rapidocr(pre: bool) -> Callable[[str], list[str]]:
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()

    def quads(path: str) -> list[tuple[str, list]]:
        img = cv2.cvtColor(preprocess(path), cv2.COLOR_GRAY2BGR) if pre else cv2.imread(path)
        result, _ = engine(img)
        return [(text, [list(map(float, p)) for p in quad]) for quad, text, _score in result or []]

    return _with_quads(quads)


def _paddleocr(pre: bool, size: str = "small") -> Callable[[str], list[str]]:
    # Keep downloaded models on the project drive instead of C:\Users\<me>\.paddlex
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(Path(__file__).resolve().parents[2] / "models" / "paddlex"))
    from paddleocr import PaddleOCR

    engine = PaddleOCR(
        text_detection_model_name=f"PP-OCRv6_{size}_det",
        text_recognition_model_name=f"PP-OCRv6_{size}_rec",
        device="cpu",
        # PaddlePaddle 3.3's oneDNN executor crashes on Windows CPU
        # (ConvertPirAttribute2RuntimeAttribute NotImplementedError).
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    def quads(path: str) -> list[tuple[str, list]]:
        img = cv2.cvtColor(preprocess(path), cv2.COLOR_GRAY2BGR) if pre else cv2.imread(path)
        return [(text, poly.tolist()) for res in engine.predict(img) for text, poly in zip(res["rec_texts"], res["rec_polys"])]

    return _with_quads(quads)


ENGINES = {
    "tesseract": _tesseract,
    "rapidocr": _rapidocr,
    "paddleocr": _paddleocr,
    "paddleocr-medium": lambda pre: _paddleocr(pre, "medium"),
}


DEFAULT_ENGINE = "paddleocr"  # chosen by benchmark, see docs/01-ocr-selection.md


def load_engine(name: str = DEFAULT_ENGINE, preprocess_image: bool = False) -> Callable[[str], list[str]]:
    return ENGINES[name](preprocess_image)
