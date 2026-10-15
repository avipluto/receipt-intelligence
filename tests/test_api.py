import sys
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receipt_ai import api, pipeline  # noqa: E402
from receipt_ai.ask import Route  # noqa: E402
from receipt_ai.extract import Extraction  # noqa: E402
from receipt_ai.schema import LineItem, RawReceipt, Receipt  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(api, "UPLOAD_DIR", tmp_path / "uploads")

    def fake_extract(lines):
        raw = RawReceipt(merchant="Cafe", date="14/09/2026", subtotal="100.00", tax="20.00", total="120.00")
        r = Receipt.from_raw(raw)
        r.items = [LineItem(name="Coffee", line_total=100)]
        return Extraction(r, raw.model_dump_json(), 0.01)

    monkeypatch.setattr(pipeline, "extract", fake_extract)
    return TestClient(api.app)


def _pdf_bytes(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


def test_upload_then_fetch_and_cite(client):
    pdf = _pdf_bytes("Cafe receipt  Coffee 100.00  Tax 20.00  TOTAL 120.00")
    r = client.post("/receipts", files={"file": ("r.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] and body["receipt"]["total"] == "120.00"  # money as a string, never a float
    rid = body["receipt_id"]

    detail = client.get(f"/receipts/{rid}").json()
    assert detail["merchant"] == "Cafe" and "TOTAL 120.00" in detail["ocr_text"]
    assert client.get(f"/receipts/{rid}/file").content == pdf

    # Same file again: recognised as a duplicate, not counted twice.
    again = client.post("/receipts", files={"file": ("copy.pdf", pdf, "application/pdf")}).json()
    assert again["duplicate"] and again["receipt_id"] == rid
    assert len(client.get("/receipts").json()) == 1


def test_rejects_bad_uploads(client):
    assert client.post("/receipts", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415
    assert client.post("/receipts", files={"file": ("x.png", b"", "image/png")}).status_code == 400


def test_missing_receipt_is_404(client):
    assert client.get("/receipts/999").status_code == 404
    assert client.delete("/receipts/999").status_code == 404


def test_ask_returns_answer_and_citations(client, monkeypatch):
    pdf = _pdf_bytes("Cafe receipt  Coffee 100.00  TOTAL 120.00")
    rid = client.post("/receipts", files={"file": ("r.pdf", pdf, "application/pdf")}).json()["receipt_id"]

    from receipt_ai import ask as ask_mod

    monkeypatch.setattr(ask_mod, "route", lambda q, today: Route(tool="total_spent", period="all"))
    r = client.post("/ask", json={"question": "How much did I spend?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "120.00" in body["answer"] and body["receipt_ids"] == [rid] and not body["used_llm"]


def test_stats_endpoints(client):
    client.post("/receipts", files={"file": ("r.pdf", _pdf_bytes("Cafe receipt  Coffee 100.00  TOTAL 120.00"), "application/pdf")})
    assert client.get("/stats/monthly").json()["rows"] == [{"month": "2026-09", "receipts": 1, "total": "120.00"}]
    assert client.get("/stats/merchants").json()["rows"][0]["merchant"] == "Cafe"
