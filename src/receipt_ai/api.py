"""HTTP API over the pipeline, the database and the question answering.

  uvicorn receipt_ai.api:app --app-dir src --port 8765                  (this laptop only)
  RECEIPTS_API_TOKEN=... uvicorn ... --host 0.0.0.0 --port 8765          (phone app over Wi-Fi)

Design notes:
  - One SQLite connection per request: sqlite3 connections must not be shared
    across threads, and FastAPI runs plain `def` endpoints in a thread pool.
  - Ingestion is serialised with a lock. There is one PaddleOCR engine and one
    4 GB GPU; two uploads at once would not finish sooner, only fight for memory.
  - Money goes out as strings ("552600.00"), never floats, the same rule as in the DB.
  - Every answer returns the receipt ids it is based on; /receipts/{id} and
    /receipts/{id}/file let a client show the original as a citation.
  - Access key: when RECEIPTS_API_TOKEN is set, every request must send it in an
    X-API-Key header. Listening on 0.0.0.0 exposes receipts to the whole Wi-Fi
    network, so the phone app is only meant to be used with a token set.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import db, pipeline, queries
from .ask import ask
from .extract import OLLAMA_URL

DB_PATH = os.environ.get("RECEIPTS_DB", "data/db/receipts.db")
UPLOAD_DIR = Path(os.environ.get("RECEIPTS_UPLOADS", "data/raw"))
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_TYPES = pipeline.IMAGE_TYPES | {".pdf"}


def require_token(x_api_key: str | None = Header(default=None)) -> None:
    token = os.environ.get("RECEIPTS_API_TOKEN")
    if not token:
        return  # no token configured: local-only use
    # compare_digest takes the same time for any wrong key, so timing can't leak the token.
    if x_api_key is None or not secrets.compare_digest(x_api_key, token):
        raise HTTPException(401, "missing or wrong X-API-Key")


app = FastAPI(title="Receipt Intelligence", version="0.2.0", dependencies=[Depends(require_token)])
_ingest_lock = threading.Lock()


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def _money(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


def _jsonable(rows: list[dict]) -> list[dict]:
    return [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items()} for r in rows]


# ---------------------------------------------------------------- health


@app.get("/health")
def health(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).raise_for_status()
        ollama = "ok"
    except requests.RequestException as e:
        ollama = f"unreachable: {type(e).__name__}"
    receipts = conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    return {"ollama": ollama, "receipts": receipts}


# ---------------------------------------------------------------- receipts


@app.post("/receipts", status_code=201)
def upload_receipt(file: UploadFile, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_TYPES:
        raise HTTPException(415, f"unsupported file type {suffix!r}; use one of {sorted(ALLOWED_TYPES)}")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if not data:
        raise HTTPException(400, "empty file")

    # Name the stored file by its content hash: the same upload twice is one file,
    # and the DB's UNIQUE(file_sha256) already makes it one receipt.
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{hashlib.sha256(data).hexdigest()}{suffix}"
    if not path.exists():
        path.write_bytes(data)

    with _ingest_lock:
        result = pipeline.ingest(path, conn)
    if result.error:
        raise HTTPException(422, f"could not read receipt: {result.error}")
    return {
        "receipt_id": result.receipt_id,
        "created": result.created,
        "duplicate": result.text_source == "cached",
        "text_source": result.text_source,
        "timings": result.timings,
        "receipt": _receipt_json(result.receipt),
    }


def _receipt_json(r) -> dict:
    return {
        "merchant": r.merchant,
        "date": r.date.isoformat() if r.date else None,
        "currency": r.currency,
        "subtotal": _money(r.subtotal),
        "tax": _money(r.tax),
        "service_charge": _money(r.service_charge),
        "discount": _money(r.discount),
        "total": _money(r.total),
        "payment_method": r.payment_method,
        "needs_review": r.needs_review,
        "issues": r.issues,
        "items": [
            {"name": i.name, "quantity": _money(i.quantity), "unit_price": _money(i.unit_price), "line_total": _money(i.line_total)}
            for i in r.items
        ],
    }


@app.get("/receipts")
def list_receipts(start: date | None = None, end: date | None = None, merchant: str | None = None,
                  limit: int = 100, conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    res = queries.list_receipts(conn, start and start.isoformat(), end and end.isoformat(), merchant, limit)
    return _jsonable(res.rows)


@app.get("/receipts/{receipt_id}")
def get_receipt(receipt_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    r = db.load_receipt(conn, receipt_id)
    if r is None:
        raise HTTPException(404, "no such receipt")
    row = conn.execute("SELECT file_path, ocr_text, created_at FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    return {"receipt_id": receipt_id, **_receipt_json(r), "ocr_text": row["ocr_text"],
            "file_name": Path(row["file_path"]).name, "created_at": row["created_at"]}


@app.get("/receipts/{receipt_id}/file")
def get_receipt_file(receipt_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> FileResponse:
    row = conn.execute("SELECT file_path FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such receipt")
    path = Path(row["file_path"])
    if not path.is_file():
        raise HTTPException(410, "original file is no longer on disk")
    return FileResponse(path)


@app.delete("/receipts/{receipt_id}", status_code=204)
def delete_receipt(receipt_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> None:
    with conn:
        cur = conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))  # items cascade
    if cur.rowcount == 0:
        raise HTTPException(404, "no such receipt")


# ---------------------------------------------------------------- questions and charts


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/ask")
def ask_question(q: Question, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        a = ask(conn, q.question)
    except requests.RequestException as e:
        raise HTTPException(503, f"local LLM unavailable: {type(e).__name__}") from e
    return {
        "question": a.question,
        "answer": a.text,
        "used_llm": a.used_llm,
        "period": a.period_text,
        "route": a.route.model_dump(exclude_none=True),
        "rows": _jsonable(a.result.rows),
        "receipt_ids": a.result.receipt_ids,  # citations
        "needs_review": a.result.needs_review,
        "note": a.result.note,
    }


@app.get("/stats/monthly")
def stats_monthly(start: date | None = None, end: date | None = None, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    res = queries.spend_by_month(conn, start and start.isoformat(), end and end.isoformat())
    return {"rows": _jsonable(res.rows), "note": res.note}


@app.get("/stats/merchants")
def stats_merchants(start: date | None = None, end: date | None = None, top_n: int = 10,
                    conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    res = queries.spend_by_merchant(conn, start and start.isoformat(), end and end.isoformat(), top_n)
    return {"rows": _jsonable(res.rows)}
