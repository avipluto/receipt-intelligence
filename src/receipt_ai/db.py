"""SQLite storage for receipts and their line items.

Design notes:
  - stdlib sqlite3, no ORM: two tables don't justify the dependency, and the SQL
    stays visible (the query layer later generates SQL against this schema).
  - Money is INTEGER hundredths ("cents"). SQLite has no exact decimal type and
    REAL would reintroduce float drift; integers are exact and SUM() works.
  - The OCR text and raw LLM JSON are kept so answers can cite their source receipt
    and extractions can be re-run or audited later.
  - file_sha256 is UNIQUE: re-uploading the same file never double-counts spending.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from .schema import LineItem, Receipt

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    id              INTEGER PRIMARY KEY,
    file_path       TEXT NOT NULL,
    file_sha256     TEXT NOT NULL UNIQUE,
    merchant        TEXT,
    purchase_date   TEXT,              -- ISO YYYY-MM-DD, sorts and compares as text
    currency        TEXT,
    subtotal_cents  INTEGER,
    tax_cents       INTEGER,
    total_cents     INTEGER,
    payment_method  TEXT,
    needs_review    INTEGER NOT NULL DEFAULT 0,
    issues          TEXT NOT NULL DEFAULT '[]',   -- JSON list of strings
    ocr_text        TEXT NOT NULL,
    raw_json        TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS items (
    id               INTEGER PRIMARY KEY,
    receipt_id       INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    quantity         REAL,
    unit_price_cents INTEGER,
    line_total_cents INTEGER
);

CREATE INDEX IF NOT EXISTS idx_receipts_date     ON receipts(purchase_date);
CREATE INDEX IF NOT EXISTS idx_receipts_merchant ON receipts(merchant);
CREATE INDEX IF NOT EXISTS idx_items_receipt     ON items(receipt_id);
"""


def to_cents(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_cents(value: int | None) -> Decimal | None:
    return None if value is None else Decimal(value) / 100


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def connect(path: str | Path = "data/db/receipts.db") -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # off by default in SQLite
    conn.executescript(SCHEMA)
    return conn


def save_receipt(
    conn: sqlite3.Connection,
    receipt: Receipt,
    *,
    file_path: str,
    sha256: str,
    ocr_lines: list[str],
    raw_json: str,
) -> tuple[int, bool]:
    """Insert a receipt and its items. Returns (receipt_id, created).

    If the same file was saved before, returns the existing id with created=False.
    Receipt + items are written in one transaction: either both land or neither does.
    """
    existing = conn.execute("SELECT id FROM receipts WHERE file_sha256 = ?", (sha256,)).fetchone()
    if existing:
        return existing["id"], False

    with conn:  # transaction: commits on success, rolls back on exception
        cur = conn.execute(
            """INSERT INTO receipts (file_path, file_sha256, merchant, purchase_date, currency,
                   subtotal_cents, tax_cents, total_cents, payment_method,
                   needs_review, issues, ocr_text, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                file_path, sha256, receipt.merchant,
                receipt.date.isoformat() if receipt.date else None,
                receipt.currency,
                to_cents(receipt.subtotal), to_cents(receipt.tax), to_cents(receipt.total),
                receipt.payment_method,
                int(receipt.needs_review), json.dumps(receipt.issues),
                "\n".join(ocr_lines), raw_json,
            ),
        )
        receipt_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO items (receipt_id, name, quantity, unit_price_cents, line_total_cents) VALUES (?, ?, ?, ?, ?)",
            [
                (receipt_id, i.name, float(i.quantity) if i.quantity is not None else None,
                 to_cents(i.unit_price), to_cents(i.line_total))
                for i in receipt.items
            ],
        )
    return receipt_id, True


def load_receipt(conn: sqlite3.Connection, receipt_id: int) -> Receipt | None:
    row = conn.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    if row is None:
        return None
    items = conn.execute("SELECT * FROM items WHERE receipt_id = ? ORDER BY id", (receipt_id,)).fetchall()
    return Receipt(
        merchant=row["merchant"],
        date=row["purchase_date"],
        currency=row["currency"],
        subtotal=from_cents(row["subtotal_cents"]),
        tax=from_cents(row["tax_cents"]),
        total=from_cents(row["total_cents"]),
        payment_method=row["payment_method"],
        issues=json.loads(row["issues"]),
        items=[
            LineItem(
                name=i["name"],
                quantity=Decimal(str(i["quantity"])) if i["quantity"] is not None else None,
                unit_price=from_cents(i["unit_price_cents"]),
                line_total=from_cents(i["line_total_cents"]),
            )
            for i in items
        ],
    )
