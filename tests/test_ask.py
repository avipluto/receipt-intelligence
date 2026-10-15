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
