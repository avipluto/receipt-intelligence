import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receipt_ai import db, queries  # noqa: E402
from receipt_ai.schema import LineItem, Receipt  # noqa: E402


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    data = [
        ("BIG BAZAAR #1142", date(2026, 9, 3), "552.30", [("Amul Butter 500g", "285.00"), ("Tata Salt", "56.00")], []),
        ("Big Bazaar", date(2026, 9, 20), "100.00", [("Bread", "45.00")], []),
        ("Cafe Coffee Day", date(2026, 9, 25), "240.00", [("Latte", "240.00")], ["items sum mismatch"]),
        ("Cafe Coffee Day", date(2026, 10, 2), "180.00", [("Butter croissant", "180.00")], []),
        ("Unknown shop", None, "99.00", [], []),
    ]
    for i, (merchant, d, total, items, issues) in enumerate(data):
        r = Receipt(merchant=merchant, date=d, total=Decimal(total), issues=issues,
                    items=[LineItem(name=n, line_total=Decimal(p)) for n, p in items])
        db.save_receipt(c, r, file_path=f"{i}.jpg", sha256=str(i), ocr_lines=[], raw_json="{}")
    yield c
    c.close()


def test_total_spent_in_september(conn):
    r = queries.total_spent(conn, "2026-09-01", "2026-09-30")
    assert r.rows[0]["total"] == Decimal("892.30")
    assert r.rows[0]["receipts"] == 3
    assert r.receipt_ids == [1, 2, 3]
    assert r.needs_review == 1


def test_end_date_is_inclusive(conn):
    assert queries.total_spent(conn, "2026-09-25", "2026-09-25").rows[0]["total"] == Decimal("240.00")


def test_merchant_filter_is_case_insensitive_substring(conn):
    r = queries.total_spent(conn, merchant="bazaar")
    assert r.rows[0]["total"] == Decimal("652.30")


def test_no_matches_gives_zero_not_none(conn):
    r = queries.total_spent(conn, "2030-01-01", "2030-12-31")
    assert r.rows[0]["total"] == Decimal("0") and r.receipt_ids == []


def test_spend_by_merchant_ranks_largest_first(conn):
    rows = queries.spend_by_merchant(conn).rows
    assert rows[0]["merchant"] == "BIG BAZAAR #1142"
    assert [r["total"] for r in rows] == sorted((r["total"] for r in rows), reverse=True)


def test_spend_by_month_reports_undated_receipts(conn):
    r = queries.spend_by_month(conn)
    assert [(x["month"], x["total"]) for x in r.rows] == [("2026-09", Decimal("892.30")), ("2026-10", Decimal("180.00"))]
    assert "1 receipt" in r.note


def test_find_items_matches_across_receipts(conn):
    r = queries.find_items(conn, "butter")
    assert {x["item"] for x in r.rows} == {"Amul Butter 500g", "Butter croissant"}
    assert r.receipt_ids == [1, 4]


def test_find_items_respects_dates(conn):
    r = queries.find_items(conn, "butter", start="2026-10-01")
    assert [x["item"] for x in r.rows] == ["Butter croissant"]


def test_sql_injection_in_arguments_is_just_text(conn):
    r = queries.total_spent(conn, merchant="x' OR '1'='1")
    assert r.rows[0]["receipts"] == 0
    assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 5


def test_to_dict_is_json_safe(conn):
    import json

    json.dumps(queries.total_spent(conn).to_dict())
