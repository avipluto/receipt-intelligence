import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receipt_ai.ask import Route, grounded, numbers_in, resolve_period  # noqa: E402

TODAY = date(2026, 10, 15)


@pytest.mark.parametrize(
    "kw, expected",
    [
        (dict(period="this_month"), ("2026-10-01", "2026-10-15")),
        (dict(period="last_month"), ("2026-09-01", "2026-09-30")),
        (dict(period="month", month=9), ("2026-09-01", "2026-09-30")),
        (dict(period="month", month=11), ("2025-11-01", "2025-11-30")),  # November hasn't happened yet this year
        (dict(period="month", month=2, year=2024), ("2024-02-01", "2024-02-29")),  # leap year
        (dict(period="this_year"), ("2026-01-01", "2026-10-15")),
        (dict(period="last_year"), ("2025-01-01", "2025-12-31")),
        (dict(period="last_n_days", n_days=7), ("2026-10-09", "2026-10-15")),
        (dict(period="all"), (None, None)),
        (dict(period="month"), (None, None)),  # month missing -> fall back to all time, don't crash
        (dict(period="range", start="2026-09-01", end="2026-09-30"), ("2026-09-01", "2026-09-30")),
        (dict(period="range", start="2026-09-30", end="2026-09-01"), ("2026-09-01", "2026-09-30")),  # reversed
        (dict(period="range", start="2026-9-1", end="30 Sept"), (None, None)),  # not ISO: would match nothing as text
        (dict(period="range", start="2026-09-01"), (None, None)),
        (dict(period="last_n_days", n_days=-5), (None, None)),
        (dict(period="last_n_days", n_days=3000000000000000), (None, None)),  # measured live; overflowed timedelta
        (dict(period="year", year=99999), (None, None)),  # date() would raise
        (dict(period="month", month=9, year=0), ("2026-09-01", "2026-09-30")),  # junk year ignored, month kept
    ],
)
def test_resolve_period(kw, expected):
    start, end, _ = resolve_period(Route(tool="total_spent", **kw), TODAY)
    assert (start, end) == expected


def test_last_month_in_january_wraps_year():
    start, end, text = resolve_period(Route(tool="total_spent", period="last_month"), date(2027, 1, 10))
    assert (start, end, text) == ("2026-12-01", "2026-12-31", "December 2026")


def test_numbers_in_handles_commas_and_trailing_zeros():
    assert numbers_in("You spent 1,250.50 and 892.3") == numbers_in("1250.5 892.30")


def test_grounded_accepts_numbers_from_data():
    allowed = numbers_in('{"total": "892.30", "receipts": 3}')
    assert grounded("You spent 892.30 across 3 receipts.", allowed)
    assert grounded("You spent 892.3.", allowed)


def test_grounded_rejects_invented_or_rounded_numbers():
    allowed = numbers_in('{"total": "892.30", "receipts": 3}')
    assert not grounded("You spent about 900.", allowed)
    assert not grounded("That's 297.43 per receipt.", allowed)  # computed, not in data


def _junk_route(**kw):
    base = dict(tool="total_spent", period="this_month", month=10, year=2026, n_days=3000000000000000,
                start="2026-10-01", end="2026-10-15", merchant="Big Bazaar", item="butter")
    base.update(kw)
    return Route(**base)


def test_sanitize_drops_period_the_question_never_mentions():
    from receipt_ai.ask import sanitize_route

    r = sanitize_route("How much did I spend in total?", _junk_route())
    assert r.period == "all" and r.merchant is None and r.item is None
    assert r.month is r.year is r.n_days is r.start is r.end is None


def test_sanitize_keeps_values_found_in_the_question():
    from receipt_ai.ask import sanitize_route

    r = sanitize_route("How much did I spend at Big Bazaar in September 2025?", _junk_route(period="month", month=9, year=2025))
    assert (r.period, r.month, r.year, r.merchant) == ("month", 9, 2025, "Big Bazaar")
    r = sanitize_route("When did I last buy butter?", _junk_route(tool="find_items", period="all"))
    assert r.item == "butter" and r.merchant is None
    r = sanitize_route("Spending in the last 10 days", _junk_route(period="last_n_days", n_days=10))
    assert r.n_days == 10


def test_total_uses_template_not_llm(monkeypatch):
    from receipt_ai import ask as ask_mod
    from receipt_ai.queries import QueryResult

    monkeypatch.setattr(ask_mod, "_chat", lambda *a, **k: pytest.fail("LLM should not phrase a single total"))
    res = QueryResult(rows=[{"total": "552600", "receipts": 8}], receipt_ids=list(range(1, 9)))
    text, used_llm = ask_mod.answer("How much in total?", Route(tool="total_spent", period="all"), res, "all time", date(2026, 10, 15))
    assert not used_llm and "552600" in text and "8 receipt" in text


def test_todays_date_in_answer_is_not_grounded(monkeypatch):
    # Measured live: the model dated an undated receipt with today's date.
    from receipt_ai import ask as ask_mod
    from receipt_ai.queries import QueryResult

    monkeypatch.setattr(ask_mod, "_chat", lambda *a, **k: "You bought COFFEE for 82000 on 2026-10-15.")
    res = QueryResult(rows=[{"item": "COFFEE", "quantity": None, "line_total": "82000", "merchant": None, "date": None, "receipt_id": 5}], receipt_ids=[5])
    text, used_llm = ask_mod.answer("Did I buy coffee?", Route(tool="find_items", period="all", item="coffee"), res, "all time", date(2026, 10, 15))
    assert not used_llm and "2026" not in text and "None" not in text and "82000" in text


def test_review_note_is_appended_by_python():
    from receipt_ai.ask import REVIEW_NOTE, with_review_note
    from receipt_ai.queries import QueryResult

    assert with_review_note("You spent 10.", QueryResult(rows=[], needs_review=1)).endswith(REVIEW_NOTE)
    assert with_review_note("You spent 10.", QueryResult(rows=[])) == "You spent 10."


def test_invented_currency_symbol_is_removed():
    from receipt_ai.ask import strip_invented_currency

    assert strip_invented_currency("I paid $909.00 for chicken.", '{"line_total": "909.00"}') == "I paid 909.00 for chicken."
    assert strip_invented_currency("I paid Rp 909.00.", '{"currency": "Rp"}') == "I paid Rp 909.00."
