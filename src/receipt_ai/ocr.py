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
    h: float  # height


def group_lines(boxes: list[Box]) -> list[str]:
    """Merge word/segment boxes into printed lines.

    Detectors like PaddleOCR return segments, not lines: "TOTAL" and "31.000" on a
    receipt are often separate boxes far apart horizontally. Two boxes belong to the
    same line when their vertical centres are within half a box height.
    """
    lines: list[list[Box]] = []
    for b in sorted(boxes, key=lambda b: b.y):
        if lines:
            ref = lines[-1]
            ref_y = sum(r.y for r in ref) / len(ref)
            ref_h = sum(r.h for r in ref) / len(ref)
            if abs(b.y - ref_y) < 0.5 * max(ref_h, b.h):
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

    def run(path: str) -> list[str]:
        img = cv2.cvtColor(preprocess(path), cv2.COLOR_GRAY2BGR) if pre else cv2.imread(path)
        result, _ = engine(img)
        boxes = []
        for quad, text, _score in result or []:
            ys = [p[1] for p in quad]
            boxes.append(Box(text, min(p[0] for p in quad), sum(ys) / 4, max(ys) - min(ys)))
        return group_lines(boxes)

    return run


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

    def run(path: str) -> list[str]:
        img = cv2.cvtColor(preprocess(path), cv2.COLOR_GRAY2BGR) if pre else cv2.imread(path)
        boxes = []
        for res in engine.predict(img):
            for text, poly in zip(res["rec_texts"], res["rec_polys"]):
                ys = poly[:, 1]
                boxes.append(Box(text, float(poly[:, 0].min()), float(ys.mean()), float(ys.max() - ys.min())))
        return group_lines(boxes)

    return run


ENGINES = {
    "tesseract": _tesseract,
    "rapidocr": _rapidocr,
    "paddleocr": _paddleocr,
    "paddleocr-medium": lambda pre: _paddleocr(pre, "medium"),
}


DEFAULT_ENGINE = "paddleocr"  # chosen by benchmark, see docs/01-ocr-selection.md


def load_engine(name: str = DEFAULT_ENGINE, preprocess_image: bool = False) -> Callable[[str], list[str]]:
    return ENGINES[name](preprocess_image)
