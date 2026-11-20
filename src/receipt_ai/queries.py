"""Spending queries: the only way the assistant gets numbers out of the database.

The LLM never writes SQL. It picks one of these functions and fills in arguments;
the function runs fixed, parameterised SQL. Every result carries the receipt ids it
was computed from, so each answer can cite its sources.

Dates are ISO strings 'YYYY-MM-DD'; start is inclusive, end is inclusive.
Receipts flagged needs_review are included but counted, so answers can say
"2 of these receipts need checking".
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .db import from_cents


@dataclass
class QueryResult:
    rows: list[dict]
    receipt_ids: list[int] = field(default_factory=list)
    needs_review: int = 0  # how many cited receipts are flagged
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        # Decimal -> str so the result can go into JSON / an LLM prompt unchanged.
        d["rows"] = [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items()} for r in self.rows]
        return d


def _like(term: str) -> str:
    """Substring pattern for LIKE, with the term's own % and _ taken literally.

    Without this, asking about a merchant called "%" (or an item "_") matched every row.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


_ESCAPE = "ESCAPE '\\'"  # goes after every LIKE that takes a _like() pattern


def _where(start: str | None, end: str | None, merchant: str | None, prefix: str = "",
           require_total: bool = True) -> tuple[str, list]:
    """Build a parameterised WHERE clause. Values always go in `params`, never into the SQL text."""
    p = prefix
    # Sums skip receipts with no total. Listings must not: a receipt whose total could
    # not be read is exactly the one the user has to open and check.
    clauses, params = ([f"{p}total_cents IS NOT NULL"] if require_total else ["1=1"]), []
    if start:
        clauses.append(f"{p}purchase_date >= ?")
        params.append(start)
    if end:
        clauses.append(f"{p}purchase_date <= ?")
        params.append(end)
    if merchant:
        # Case-insensitive substring: "bazaar" matches "BIG BAZAAR #1142".
        # (LIKE already ignores ASCII case in SQLite.)
        clauses.append(f"{p}merchant LIKE ? {_ESCAPE}")
        params.append(_like(merchant))
    return " AND ".join(clauses), params


def _cited(conn: sqlite3.Connection, where: str, params: list) -> tuple[list[int], int]:
    rows = conn.execute(f"SELECT id, needs_review FROM receipts WHERE {where} ORDER BY purchase_date, id", params).fetchall()
    return [r["id"] for r in rows], sum(r["needs_review"] for r in rows)


def total_spent(conn, start: str | None = None, end: str | None = None, merchant: str | None = None) -> QueryResult:
    """Total amount spent, optionally within dates and/or at one merchant."""
    where, params = _where(start, end, merchant)
    row = conn.execute(f"SELECT COUNT(*) AS n, SUM(total_cents) AS cents FROM receipts WHERE {where}", params).fetchone()
    ids, review = _cited(conn, where, params)
    return QueryResult(
        rows=[{"total": from_cents(row["cents"]) or Decimal("0"), "receipts": row["n"]}],
        receipt_ids=ids, needs_review=review,
    )


def spend_by_merchant(conn, start: str | None = None, end: str | None = None, top_n: int = 10) -> QueryResult:
    """Spending grouped by merchant, largest first.

    "Cafe", "CAFE" and "cafe " are one shop printed three ways (OCR and the model both
    vary the case), so the grouping ignores case and outer spaces.
    """
    where, params = _where(start, end, None)
    name = "TRIM(COALESCE(merchant, 'Unknown'))"
    rows = conn.execute(
        f"""SELECT MIN({name}) AS merchant, COUNT(*) AS receipts, SUM(total_cents) AS cents
            FROM receipts WHERE {where}
            GROUP BY {name} COLLATE NOCASE ORDER BY cents DESC, merchant LIMIT ?""",
        [*params, top_n],
    ).fetchall()
    ids, review = _cited(conn, where, params)
    return QueryResult(
        rows=[{"merchant": r["merchant"], "receipts": r["receipts"], "total": from_cents(r["cents"])} for r in rows],
        receipt_ids=ids, needs_review=review,
    )


def spend_by_month(conn, start: str | None = None, end: str | None = None, merchant: str | None = None) -> QueryResult:
    """Spending per calendar month (YYYY-MM), oldest first. Receipts without a date are excluded and counted."""
    where, params = _where(start, end, merchant)
    rows = conn.execute(
        f"""SELECT substr(purchase_date, 1, 7) AS month, COUNT(*) AS receipts, SUM(total_cents) AS cents
            FROM receipts WHERE {where} AND purchase_date IS NOT NULL
            GROUP BY month ORDER BY month""",
        params,
    ).fetchall()
    undated = conn.execute(f"SELECT COUNT(*) FROM receipts WHERE {where} AND purchase_date IS NULL", params).fetchone()[0]
    ids, review = _cited(conn, where + " AND purchase_date IS NOT NULL", params)
    return QueryResult(
        rows=[{"month": r["month"], "receipts": r["receipts"], "total": from_cents(r["cents"])} for r in rows],
        receipt_ids=ids, needs_review=review,
        note=f"{undated} receipt(s) have no date and are not included" if undated else "",
    )


def find_items(conn, query: str, start: str | None = None, end: str | None = None, limit: int = 50) -> QueryResult:
    """Line items whose name contains `query` (case-insensitive), with their receipt and date."""
    where, params = _where(start, end, None, prefix="r.")
    rows = conn.execute(
        f"""SELECT i.name, i.quantity, i.line_total_cents, r.id AS receipt_id, r.merchant, r.purchase_date, r.needs_review
            FROM items i JOIN receipts r ON r.id = i.receipt_id
            WHERE {where} AND i.name LIKE ? {_ESCAPE}
            ORDER BY r.purchase_date, r.id LIMIT ?""",
        [*params, _like(query), limit],
    ).fetchall()
    ids = sorted({r["receipt_id"] for r in rows})
    review_ids = {r["receipt_id"] for r in rows if r["needs_review"]}
    return QueryResult(
        rows=[
            {"item": r["name"], "quantity": r["quantity"], "line_total": from_cents(r["line_total_cents"]),
             "merchant": r["merchant"], "date": r["purchase_date"], "receipt_id": r["receipt_id"]}
            for r in rows
        ],
        receipt_ids=ids, needs_review=len(review_ids),
    )


def list_receipts(conn, start: str | None = None, end: str | None = None, merchant: str | None = None, limit: int = 50) -> QueryResult:
    """Individual receipts, newest first. Includes receipts with no readable total."""
    where, params = _where(start, end, merchant, require_total=False)
    rows = conn.execute(
        f"""SELECT id, merchant, purchase_date, total_cents, needs_review FROM receipts
            WHERE {where} ORDER BY purchase_date DESC, id DESC LIMIT ?""",
        [*params, limit],
    ).fetchall()
    return QueryResult(
        rows=[{"receipt_id": r["id"], "merchant": r["merchant"], "date": r["purchase_date"],
               "total": from_cents(r["total_cents"]), "needs_review": bool(r["needs_review"])} for r in rows],
        receipt_ids=[r["id"] for r in rows], needs_review=sum(r["needs_review"] for r in rows),
    )


TOOLS = {f.__name__: f for f in (total_spent, spend_by_merchant, spend_by_month, find_items, list_receipts)}
