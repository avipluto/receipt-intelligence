import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receipt_ai import db, pipeline  # noqa: E402
from receipt_ai.extract import Extraction  # noqa: E402
from receipt_ai.schema import RawReceipt, Receipt  # noqa: E402


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the LLM with a stub that records what text it was given."""
    seen = []

    def fake_extract(lines):
        seen.append(lines)
        raw = RawReceipt(merchant="Cafe", date="14/09/2026", total="120.00")
        return Extraction(Receipt.from_raw(raw), raw.model_dump_json(), 0.01)

    monkeypatch.setattr(pipeline, "extract", fake_extract)
    return seen


def _text_pdf(path: Path, text: str) -> Path:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(path)
    return path


def test_text_pdf_skips_ocr(tmp_path, conn, fake_llm, monkeypatch):
    monkeypatch.setattr(pipeline, "_ocr", lambda: pytest.fail("OCR should not run for a text PDF"))
    pdf = _text_pdf(tmp_path / "r.pdf", "CAFE COFFEE DAY\nLATTE 120.00\nTOTAL 120.00")

    r = pipeline.ingest(pdf, conn)

    assert r.error is None and r.created
    assert r.text_source == "pdf-text"
    assert "TOTAL 120.00" in fake_llm[0]
    assert db.load_receipt(conn, r.receipt_id).total == 120


def test_duplicate_upload_skips_llm(tmp_path, conn, fake_llm):
    pdf = _text_pdf(tmp_path / "r.pdf", "CAFE COFFEE DAY\nLATTE 120.00\nTOTAL 120.00")
    first = pipeline.ingest(pdf, conn)
    second = pipeline.ingest(pdf, conn)

    assert second.receipt_id == first.receipt_id
    assert second.text_source == "cached" and not second.created
    assert len(fake_llm) == 1  # LLM called once, not twice


def test_blank_pdf_page_falls_back_to_ocr(tmp_path, conn, fake_llm, monkeypatch):
    monkeypatch.setattr(pipeline, "_ocr", lambda: (lambda img_path: ["SCANNED TOTAL 50.00"]))
    doc = pymupdf.open()
    doc.new_page()  # no text layer, like a scanned page
    doc.save(tmp_path / "scan.pdf")

    r = pipeline.ingest(tmp_path / "scan.pdf", conn)

    assert r.text_source == "ocr"
    assert fake_llm[0] == ["SCANNED TOTAL 50.00"]


def test_unsupported_file_reports_error_instead_of_raising(tmp_path, conn, fake_llm):
    f = tmp_path / "notes.docx"
    f.write_bytes(b"not a receipt")
    r = pipeline.ingest(f, conn)
    assert r.error and "unsupported" in r.error
    assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0
