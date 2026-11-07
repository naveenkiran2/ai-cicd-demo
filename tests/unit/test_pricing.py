from decimal import Decimal

import pytest

from app.pricing import apply_discount, calculate_tax, calculate_total, to_money


def test_to_money_rounds_half_up():
    assert to_money("2.345") == Decimal("2.35")


def test_no_discount_no_tax():
    assert calculate_total(100)["total"] == Decimal("100.00")


def test_ten_percent_discount_amount():
    assert apply_discount(200, 10) == Decimal("20.00")


def test_ten_percent_discount_total():
    assert calculate_total(100, discount_pct=10)["total"] == Decimal("90.00")


def test_discount_then_tax():
    result = calculate_total(100, discount_pct=10, tax_rate_pct=8)
    assert result["discount"] == Decimal("10.00")
    assert result["tax"] == Decimal("7.20")
    assert result["total"] == Decimal("97.20")


def test_tax_only():
    assert calculate_tax(50, 8.25) == Decimal("4.13")


def test_discount_out_of_range_rejected():
    with pytest.raises(ValueError):
        apply_discount(100, 120)


def test_negative_subtotal_rejected():
    with pytest.raises(ValueError):
        calculate_total(-1)
