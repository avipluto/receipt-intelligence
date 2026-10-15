import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receipt_ai import db  # noqa: E402
from receipt_ai.schema import LineItem, Receipt  # noqa: E402


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


def _receipt(**kw):
    base = dict(
        merchant="Big Bazaar", date=date(2026, 9, 14), currency="INR",
        items=[LineItem(name="Butter", quantity=Decimal("1"), unit_price=Decimal("285.00"), line_total=Decimal("285.00"))],
        subtotal=Decimal("285.00"), tax=Decimal("14.25"), total=Decimal("299.25"),
    )
    return Receipt(**{**base, **kw})


def _save(conn, receipt, sha="abc"):
    return db.save_receipt(conn, receipt, file_path="r.jpg", sha256=sha, ocr_lines=["TOTAL 299.25"], raw_json="{}")


def test_round_trip_preserves_values_exactly(conn):
    rid, created = _save(conn, _receipt())
    assert created
    loaded = db.load_receipt(conn, rid)
    assert loaded.total == Decimal("299.25")
    assert loaded.date == date(2026, 9, 14)
    assert loaded.items[0].name == "Butter"
    assert loaded.items[0].line_total == Decimal("285.00")


def test_same_file_is_not_saved_twice(conn):
    first, _ = _save(conn, _receipt(), sha="same")
    second, created = _save(conn, _receipt(), sha="same")
    assert (second, created) == (first, False)
    assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1


def test_sql_sum_is_exact(conn):
    # Classic float trap: 0.1 + 0.2. As integer cents the SQL total is exact.
    _save(conn, _receipt(total=Decimal("0.10")), sha="a")
    _save(conn, _receipt(total=Decimal("0.20")), sha="b")
    total_cents = conn.execute("SELECT SUM(total_cents) FROM receipts").fetchone()[0]
    assert db.from_cents(total_cents) == Decimal("0.30")


def test_missing_values_stay_null(conn):
    rid, _ = _save(conn, Receipt(issues=["no total found"]))
    loaded = db.load_receipt(conn, rid)
    assert loaded.total is None and loaded.date is None
    assert loaded.issues == ["no total found"]
    assert conn.execute("SELECT needs_review FROM receipts WHERE id = ?", (rid,)).fetchone()[0] == 1


def test_deleting_receipt_deletes_its_items(conn):
    rid, _ = _save(conn, _receipt())
    conn.execute("DELETE FROM receipts WHERE id = ?", (rid,))
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0


def test_failed_item_insert_rolls_back_receipt(conn, monkeypatch):
    bad = _receipt(items=[LineItem(name="x")])
    # Force the items insert to fail mid-transaction.
    monkeypatch.setattr(db, "to_cents", lambda v: (_ for _ in ()).throw(RuntimeError("boom")) if v is None else int(v * 100))
    with pytest.raises(RuntimeError):
        _save(conn, bad)
    assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0


def test_cents_rounding():
    assert db.to_cents(Decimal("5.455")) == 546  # half-up, not banker's rounding
    assert db.to_cents(None) is None


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE receipts (id INTEGER PRIMARY KEY, file_path TEXT NOT NULL, file_sha256 TEXT NOT NULL UNIQUE, "
                "merchant TEXT, purchase_date TEXT, currency TEXT, subtotal_cents INTEGER, tax_cents INTEGER, "
                "total_cents INTEGER, payment_method TEXT, needs_review INTEGER NOT NULL DEFAULT 0, "
                "issues TEXT NOT NULL DEFAULT '[]', ocr_text TEXT NOT NULL, raw_json TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT (datetime('now')))")
    old.close()
    conn = db.connect(path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(receipts)")}
    assert {"service_cents", "discount_cents"} <= cols
    rid, _ = db.save_receipt(conn, Receipt(total=Decimal("10"), service_charge=Decimal("1")), file_path="x", sha256="s", ocr_lines=[], raw_json="{}")
    assert db.load_receipt(conn, rid).service_charge == Decimal("1")
