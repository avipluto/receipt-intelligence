import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receipt_ai.schema import RawItem, RawReceipt, Receipt, parse_amount, parse_date  # noqa: E402


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("552.30", "552.30"),        # India: decimal point
        ("INR 1,250.00", "1250.00"),  # India: thousands comma + decimals
        ("₹ 45", "45"),
        ("60.000", "60000"),          # Indonesia: dot as thousands separator
        ("10,000", "10000"),
        ("1,565,938", "1565938"),     # repeated separator -> thousands
        ("1.250,50", "1250.50"),      # European
        ("4,5", "4.5"),
        ("Rp. 156000", "156000"),
        ("-60.000", "-60000"),        # discount line
        ("60.000-", "-60000"),        # trailing-minus style
        ("$12.5", "12.5"),
    ],
)
def test_parse_amount(printed, expected):
    assert parse_amount(printed) == Decimal(expected)


@pytest.mark.parametrize("printed", [None, "", "N/A", "--"])
def test_parse_amount_rejects_non_numbers(printed):
    assert parse_amount(printed) is None


def test_amounts_add_exactly():
    # The reason we use Decimal: float gives 0.30000000000000004
    assert parse_amount("0.10") + parse_amount("0.20") == Decimal("0.30")


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("14/09/2026", date(2026, 9, 14)),
        ("03/04/2026", date(2026, 4, 3)),     # day first
        ("14-09-26 18:42", date(2026, 9, 14)),  # time stripped
        ("2026-09-14", date(2026, 9, 14)),
        ("14 Sep 2026", date(2026, 9, 14)),
    ],
)
def test_parse_date(printed, expected):
    assert parse_date(printed) == expected


def test_unparseable_date_is_flagged_not_dropped_silently():
    r = Receipt.from_raw(RawReceipt(date="sometime last week", total="10"))
    assert r.date is None
    assert any("unparsed date" in i for i in r.issues)


def _receipt(**kw):
    return Receipt.from_raw(RawReceipt(**kw))


def test_consistent_receipt_has_no_issues():
    r = _receipt(
        items=[RawItem(name="Butter", line_total="285.00"), RawItem(name="Salt", line_total="56.00")],
        subtotal="341.00", tax="17.05", total="358.05", date="14/09/2026",
    )
    assert r.issues == []
    assert not r.needs_review


def test_items_matching_pre_tax_total_is_fine_without_subtotal():
    r = _receipt(items=[RawItem(name="A", line_total="100")], tax="5", total="105")
    assert r.issues == []


def test_misread_total_is_flagged():
    # OCR read 358.05 as 858.05. Items still match the subtotal, so it's the
    # subtotal + tax rule that has to catch it.
    r = _receipt(items=[RawItem(name="A", line_total="341.00")], subtotal="341.00", tax="17.05", total="858.05")
    assert r.needs_review
    assert any("subtotal" in i for i in r.issues)


def test_discount_receipt_is_flagged_for_review():
    # Known false positive we accept on purpose (see Receipt.check).
    r = _receipt(subtotal="100", total="90")
    assert r.needs_review


def test_missing_total_is_flagged():
    assert "no total found" in _receipt(merchant="X").issues


def test_blank_item_names_are_dropped():
    r = _receipt(items=[RawItem(name="  "), RawItem(name="Tea", line_total="20")], total="20")
    assert [i.name for i in r.items] == ["Tea"]
