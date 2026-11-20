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
    service_charge: str | None = Field(None, description="Service charge amount as printed")
    discount: str | None = Field(None, description="Bill-level discount amount as printed")
    # Placed BEFORE total on purpose: keys are generated in order, so the model files
    # the CASH amount here first instead of mistaking it for the total.
    cash_paid: str | None = Field(None, description="Cash/amount handed over by the customer, as printed")
    change: str | None = Field(None, description="Change given back, as printed")
    total: str | None = Field(None, description="Final amount paid, as printed")
    payment_method: str | None = None


# ---------------------------------------------------------------- parsing

_NULL_WORDS = {"", "null", "none", "n/a", "na", "-", "unknown", "not specified", "not available", "not found", "not present"}


def clean_text(text: str | None) -> str | None:
    """Small models sometimes write the *string* "null" instead of JSON null."""
    if text is None or text.strip().lower() in _NULL_WORDS:
        return None
    return text.strip()


_NOT_NUMBER = re.compile(r"[^\d.,\-]")


def parse_amount(text: str | None) -> Decimal | None:
    """Turn a printed amount into a Decimal, whatever the locale.

    Money is Decimal, never float: 0.1 + 0.2 != 0.3 in floating point, and a
    spending tracker must add up exactly.

    Separator rules (receipts use ',' and '.' both ways):
      both present        -> the one appearing last is the decimal point   1,250.50 | 1.250,50
      one kind, repeated  -> thousands separator                           1,565,938
      one kind, once, followed by exactly 3 digits -> thousands            60.000 (IDR) | 10,000
        ...unless nothing but zeros comes before it -> decimal point       0.500 (kg) | 0,250
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
        # A thousands group needs a non-zero number in front of it: "0.500" is half a
        # kilo, not five hundred. Without this a weighed item's quantity came out 1000x.
        leading_zero = len(parts) == 2 and not parts[0].strip("0")
        if len(parts) > 2 or (len(parts[-1]) == 3 and not leading_zero):
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
    "%d %b %y", "%d/%b/%Y", "%B %d, %Y", "%b %d %Y", "%Y.%m.%d",
]
# A numeric date sitting inside other words: "Date: 14/09/2026", "Mon 14-09-26 (Bill 12)".
_NUMERIC_DATE = re.compile(r"(?<!\d)\d{1,4}([/.\-])\d{1,2}\1\d{1,4}(?!\d)")


def _try_formats(text: str) -> dt.date | None:
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_date(text: str | None) -> dt.date | None:
    """Day-first parsing (India / Indonesia). 03/04/2026 -> 3 April, not March 4."""
    if not text:
        return None
    # Keep only the date part: drop times like "18:42" and extra words.
    cleaned = re.sub(r"\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?", "", text, flags=re.I).strip(" ,")
    parsed = _try_formats(cleaned)
    if parsed is None and (m := _NUMERIC_DATE.search(cleaned)):
        # The model sometimes copies the label along with the value ("Date: 14/09/2026").
        parsed = _try_formats(m.group(0))
    return parsed


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
    service_charge: Decimal | None = None
    discount: Decimal | None = None  # stored positive: the amount taken off
    # Used only to cross-check the total; not stored.
    cash_paid: Decimal | None = None
    change: Decimal | None = None
    total: Decimal | None = None
    payment_method: str | None = None
    issues: list[str] = Field(default_factory=list, description="Consistency problems found by check()")

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)

    @classmethod
    def from_raw(cls, raw: RawReceipt) -> "Receipt":
        r = cls(
            merchant=clean_text(raw.merchant),
            date=parse_date(clean_text(raw.date)),
            currency=clean_text(raw.currency),
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
            service_charge=parse_amount(raw.service_charge),
            discount=abs(d) if (d := parse_amount(raw.discount)) is not None else None,
            cash_paid=parse_amount(raw.cash_paid),
            change=parse_amount(raw.change),
            total=parse_amount(raw.total),
            payment_method=clean_text(raw.payment_method),
        )
        # Only flag text that looks like an attempt at a date; "Not specified" and other
        # wordings of "missing" have no digits and simply mean no date.
        r.reconcile_total()
        if raw.date and re.search(r"\d", raw.date) and r.date is None:
            r.issues.append(f"unparsed date: {raw.date!r}")
        r.issues.extend(r.check())
        return r

    def reconcile_total(self) -> None:
        """Fill or fix the total from the payment lines, in Python.

        Measured (v6, CORD): the 3B model sometimes copies CASH as the total, or fills
        cash/change and then leaves total null. Cash minus change *is* the bill, so
        Python derives it. check() then verifies it against subtotal and items, so a
        wrong repair is still flagged rather than trusted blindly.
        """
        cash, change = self.cash_paid, self.change
        if cash is None:
            return
        # change >= cash is a misread (CORD 080: change copied as 25.000 = the cash), and
        # "repairing" with it gave a total of 0. Only repair to a positive amount.
        if change is not None and 0 < change < cash and (self.total is None or self.total == cash):
            self.total = cash - change
        elif self.total is None and not change:
            self.total = cash

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

        # Deliberately strict: a false "please check" costs the user seconds while a
        # silently wrong total corrupts every spending answer built on it.
        if self.subtotal is not None and self.total is not None:
            base = self.subtotal + (self.tax or 0) + (self.service_charge or 0)
            # A discount may already be inside the subtotal (item-level) or come after it,
            # and the model can't always tell which: either reading is accepted.
            candidates = [base, base - (self.discount or 0)]
            if not any(close(self.total, c) for c in candidates):
                problems.append(
                    f"total {self.total} != subtotal {self.subtotal} + tax {self.tax or 0}"
                    f" + service {self.service_charge or 0} - discount {self.discount or 0}"
                )

        # A second, independent path to the total: what was handed over minus what came back.
        # Paying LESS than the total in cash is fine (a coupon or card covered the rest);
        # paying more and getting less change back than that is a contradiction.
        if self.cash_paid is not None and self.change is not None and self.total is not None:
            paid = self.cash_paid - self.change
            if self.change > 0 and paid > self.total and not close(self.total, paid):
                problems.append(f"total {self.total} != cash {self.cash_paid} - change {self.change}")

        if self.date and self.date > dt.date.today():
            problems.append(f"date {self.date} is in the future")
        return problems
