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
    r = Receipt.from_raw(RawReceipt(date="32/13/2026", total="10"))
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


def test_string_null_is_treated_as_missing():
    from receipt_ai.schema import RawReceipt, Receipt

    r = Receipt.from_raw(RawReceipt(merchant="null", date="null", currency="None", total="10.00"))
    assert r.merchant is None and r.date is None and r.currency is None
    assert not any("date" in i for i in r.issues)


def test_service_charge_and_discount_balance_the_total():
    # CORD 031: SUBTTL 85,500 + SVC CHG 10,260 + PB1 18,126 = TOTAL 113,886
    r = _receipt(subtotal="85,500", service_charge="10,260", tax="18,126", total="113,886")
    assert r.issues == []
    r = _receipt(subtotal="100.00", discount="-10.00", tax="9.00", total="99.00")
    assert r.discount == Decimal("10.00") and r.issues == []


def test_wordy_missing_date_is_not_flagged_but_garbled_date_is():
    from receipt_ai.schema import RawReceipt, Receipt

    assert Receipt.from_raw(RawReceipt(date="Not specified", total="10")).issues == []
    assert any("date" in i for i in Receipt.from_raw(RawReceipt(date="2005-", total="10")).issues)


def test_cash_minus_change_cross_checks_total():
    # CORD 015: TOTAL 63.000, CASH 70.000, CHANGED 7.000.
    assert _receipt(total="63.000", cash_paid="70.000", change="7.000").issues == []
    # Customer paid 63.000 net but the total says 60.000: contradiction, flagged.
    r = _receipt(total="60.000", cash_paid="70.000", change="7.000")
    assert any("cash" in i for i in r.issues)
    # CORD 014: a 100,000 coupon covered part of the bill, so cash - change < total. Fine.
    assert _receipt(total="281,435", cash_paid="200,000", change="18,565").issues == []
    # Exact payment (change 0) says nothing about the total.
    assert _receipt(total="63.000", cash_paid="100.000", change="0").issues == []


def test_total_repaired_from_cash_and_change():
    # Model copied CASH as the total: Python derives the bill from cash - change.
    r = _receipt(total="70.000", cash_paid="70.000", change="7.000", subtotal="63.000")
    assert r.total == Decimal("63000") and r.issues == []
    # Model left total null after filling cash/change.
    assert _receipt(cash_paid="50,000", change="12,000").total == Decimal("38000")
    # Card payment, no change: the amount paid is the bill.
    assert _receipt(cash_paid="41,000").total == Decimal("41000")
    # A repair that contradicts the subtotal is still flagged, not trusted.
    r = _receipt(cash_paid="50,000", change="12,000", subtotal="30,000")
    assert any("subtotal" in i for i in r.issues)


def test_discount_may_already_be_inside_subtotal():
    # CORD 031: the -85,500 item discount is already reflected in SUBTTL 85,500.
    r = _receipt(subtotal="85,500", tax="18,126", service_charge="10,260", discount="85,500", total="113,886")
    assert r.issues == []


def test_subtotal_copied_as_total_is_still_flagged():
    # Deliberately NOT accepting "tax-inclusive" totals (subtotal == total): it bought
    # 1-2 fewer false alarms on CORD but would hide this classic misread.
    r = _receipt(subtotal="100.00", tax="10.00", total="100.00")
    assert any("subtotal" in i for i in r.issues)


def test_change_equal_to_cash_does_not_zero_the_total():
    # CORD 080 (v9): model copied the cash amount into change as well.
    r = _receipt(subtotal="25.000", total="25.000", cash_paid="25.000", change="25.000")
    assert r.total == Decimal("25000") and not any("non-positive" in i for i in r.issues)
