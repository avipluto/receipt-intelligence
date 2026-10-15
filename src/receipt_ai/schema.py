"""Receipt data model: what the LLM returns, what we store, and how we check it.

Two layers, on purpose:
  RawReceipt -> what the LLM fills in. Every value is a string copied as printed.
                Its JSON schema is handed to Ollama, which constrains decoding so the
                output always parses.
  Receipt    -> the clean, typed record we store. Built from RawReceipt by plain Python
                (parse_amount / parse_date), so number and date handling is
                deterministic and unit-tested rather than left to the LLM.
"""

from __future__ import annotations

import re
import datetime as dt
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- LLM output


class RawItem(BaseModel):
    name: str
    quantity: str | None = None
    unit_price: str | None = None
    line_total: str | None = None


class RawReceipt(BaseModel):
    merchant: str | None = Field(None, description="Store or restaurant name")
    date: str | None = Field(None, description="Purchase date exactly as printed")
    currency: str | None = Field(None, description="Currency code or symbol if printed, e.g. INR, Rp, $")
    items: list[RawItem] = Field(default_factory=list)
    subtotal: str | None = None
    tax: str | None = Field(None, description="Total tax amount as printed")
    total: str | None = Field(None, description="Final amount paid, as printed")
    payment_method: str | None = None


# ---------------------------------------------------------------- parsing

_NOT_NUMBER = re.compile(r"[^\d.,\-]")


def parse_amount(text: str | None) -> Decimal | None:
    """Turn a printed amount into a Decimal, whatever the locale.

    Money is Decimal, never float: 0.1 + 0.2 != 0.3 in floating point, and a
    spending tracker must add up exactly.

    Separator rules (receipts use ',' and '.' both ways):
      both present        -> the one appearing last is the decimal point   1,250.50 | 1.250,50
      one kind, repeated  -> thousands separator                           1,565,938
      one kind, once, followed by exactly 3 digits -> thousands            60.000 (IDR) | 10,000
      one kind, once, otherwise                    -> decimal point        552.30 | 4,5
    """
    if not text:
        return None
    s = _NOT_NUMBER.sub("", text.replace(" ", ""))
    negative = s.startswith("-") or text.strip().endswith("-")
    # "Rp. 156000" -> ".156000": a separator at either end is punctuation, not a decimal point.
    s = s.replace("-", "").strip(".,")
    if not re.search(r"\d", s):
        return None

    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        parts = s.split(sep)
        if len(parts) > 2 or len(parts[-1]) == 3:
            s = s.replace(sep, "")
        else:
            s = s.replace(sep, ".")
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


_DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
    "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%b-%y", "%b %d, %Y", "%Y/%m/%d",
]


def parse_date(text: str | None) -> dt.date | None:
    """Day-first parsing (India / Indonesia). 03/04/2026 -> 3 April, not March 4."""
    if not text:
        return None
    # Keep only the date part: drop times like "18:42" and extra words.
    cleaned = re.sub(r"\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?", "", text, flags=re.I).strip(" ,")
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- clean record


class LineItem(BaseModel):
    name: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None


class Receipt(BaseModel):
    merchant: str | None = None
    # Type written as dt.date: a field named 'date' would shadow the 'date' type.
    date: dt.date | None = None
    currency: str | None = None
    items: list[LineItem] = Field(default_factory=list)
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    payment_method: str | None = None
    issues: list[str] = Field(default_factory=list, description="Consistency problems found by check()")

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)

    @classmethod
    def from_raw(cls, raw: RawReceipt) -> "Receipt":
        r = cls(
            merchant=(raw.merchant or "").strip() or None,
            date=parse_date(raw.date),
            currency=(raw.currency or "").strip() or None,
            items=[
                LineItem(
                    name=i.name.strip(),
                    quantity=parse_amount(i.quantity),
                    unit_price=parse_amount(i.unit_price),
                    line_total=parse_amount(i.line_total),
                )
                for i in raw.items
                if i.name and i.name.strip()
            ],
            subtotal=parse_amount(raw.subtotal),
            tax=parse_amount(raw.tax),
            total=parse_amount(raw.total),
            payment_method=(raw.payment_method or "").strip() or None,
        )
        if raw.date and r.date is None:
            r.issues.append(f"unparsed date: {raw.date!r}")
        r.issues.extend(r.check())
        return r

    def check(self, tolerance: Decimal = Decimal("0.02")) -> list[str]:
        """Arithmetic sanity checks. The LLM can misread; maths can't lie.

        Returns human-readable problems instead of raising, so a receipt with a
        suspicious total is still saved but flagged for review in the UI.
        """
        problems = []
        if self.total is None:
            problems.append("no total found")
        elif self.total <= 0:
            problems.append(f"non-positive total {self.total}")

        def close(a: Decimal, b: Decimal) -> bool:
            return abs(a - b) <= max(Decimal("1"), abs(b) * tolerance)

        # The item lines should add up to *something* printed on the receipt: the
        # subtotal, the total, or the total before tax. Discounts and service charges
        # vary too much between shops to model, so any one match is enough.
        line_totals = [i.line_total for i in self.items if i.line_total is not None]
        if line_totals and self.total is not None:
            items_sum = sum(line_totals)
            targets = [t for t in (self.subtotal, self.total, self.total - (self.tax or 0)) if t is not None]
            if not any(close(items_sum, t) for t in targets):
                problems.append(f"items sum to {items_sum} but total is {self.total}")

        # Deliberately strict: discounts and service charges also trip this, but a
        # false "please check" costs the user seconds while a silently wrong total
        # corrupts every spending answer built on it.
        if self.subtotal is not None and self.total is not None:
            expected = self.subtotal + (self.tax or 0)
            if not close(self.total, expected):
                problems.append(f"total {self.total} != subtotal {self.subtotal} + tax {self.tax or 0}")

        if self.date and self.date > dt.date.today():
            problems.append(f"date {self.date} is in the future")
        return problems
