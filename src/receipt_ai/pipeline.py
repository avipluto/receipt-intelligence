"""File in -> receipt row out: text extraction -> LLM extraction -> validation -> SQLite.

PDFs with a real text layer (e-receipts, invoices) skip OCR entirely: their text is
exact and free. Only scanned PDFs and photos go through PaddleOCR.

  python -m receipt_ai.pipeline path/to/receipt.jpg [more files...]
"""

from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import db
from .extract import extract
from .ocr import load_engine
from .schema import Receipt

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
MIN_PDF_TEXT_CHARS = 30  # less than this on a page -> treat it as a scan


@dataclass
class IngestResult:
    path: str
    receipt_id: int | None = None
    created: bool = False
    receipt: Receipt | None = None
    text_source: str = ""  # "pdf-text" | "ocr" | "cached"
    error: str | None = None
    timings: dict[str, float] = field(default_factory=dict)


@lru_cache(maxsize=1)
def _ocr():
    # Loading PaddleOCR takes ~10-30 s; do it once per process, and only if needed.
    return load_engine()


def text_lines(path: Path) -> tuple[list[str], str]:
    suffix = path.suffix.lower()
    if suffix in IMAGE_TYPES:
        return _ocr()(str(path)), "ocr"
    if suffix == ".pdf":
        import pymupdf

        lines: list[str] = []
        source = "pdf-text"
        with pymupdf.open(path) as doc:
            for page in doc:
                text = page.get_text("text", sort=True)
                if len(text.strip()) >= MIN_PDF_TEXT_CHARS:
                    lines += [ln.strip() for ln in text.splitlines() if ln.strip()]
                else:
                    # Scanned page: render at 200 dpi (enough for OCR, small enough to be quick).
                    source = "ocr"
                    with tempfile.TemporaryDirectory() as tmp:
                        png = Path(tmp, "page.png")
                        page.get_pixmap(dpi=200).save(png)
                        lines += _ocr()(str(png))
        return lines, source
    raise ValueError(f"unsupported file type: {suffix}")


def ingest(path: str | Path, conn: sqlite3.Connection) -> IngestResult:
    import time

    path = Path(path)
    result = IngestResult(path=str(path))
    try:
        sha = db.file_sha256(path)
        row = conn.execute("SELECT id FROM receipts WHERE file_sha256 = ?", (sha,)).fetchone()
        if row:  # check before OCR/LLM: a duplicate costs nothing
            result.receipt_id, result.text_source = row["id"], "cached"
            result.receipt = db.load_receipt(conn, row["id"])
            return result

        t = time.perf_counter()
        lines, result.text_source = text_lines(path)
        result.timings["text_s"] = round(time.perf_counter() - t, 2)
        if not lines:
            result.error = "no text found in file"
            return result

        extraction = extract(lines)
        result.timings["llm_s"] = round(extraction.seconds, 2)
        if extraction.error:
            result.error = extraction.error
            return result

        result.receipt = extraction.receipt
        result.receipt_id, result.created = db.save_receipt(
            conn, extraction.receipt, file_path=str(path.resolve()), sha256=sha,
            ocr_lines=lines, raw_json=extraction.raw_json,
        )
    except Exception as e:  # one bad file must not stop a batch upload
        result.error = f"{type(e).__name__}: {e}"
    return result


if __name__ == "__main__":
    import sys

    conn = db.connect()
    for p in sys.argv[1:]:
        r = ingest(p, conn)
        if r.error:
            print(f"FAIL  {p}: {r.error}")
            continue
        rc = r.receipt
        flag = "REVIEW" if rc.needs_review else "OK    "
        print(f"{flag} #{r.receipt_id} {rc.merchant} {rc.date} total={rc.total} via {r.text_source} {r.timings} {rc.issues}")
