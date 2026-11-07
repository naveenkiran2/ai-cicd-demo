from decimal import Decimal

import pytest

from app.orders import LineItem, build_quote, parse_items


def test_line_total():
    assert LineItem("SKU-1", 3, Decimal("9.99")).line_total == Decimal("29.97")


def test_quote_without_discount():
    quote = build_quote([LineItem("SKU-1", 2, Decimal("25.00"))], tax_rate_pct=10)
    assert quote["subtotal"] == "50.00"
    assert quote["total"] == "55.00"
    assert quote["currency"] == "USD"


def test_quote_with_discount():
    items = [LineItem("SKU-1", 1, Decimal("80.00")), LineItem("SKU-2", 2, Decimal("10.00"))]
    quote = build_quote(items, discount_pct=25, tax_rate_pct=0)
    assert quote["discount"] == "25.00"
    assert quote["total"] == "75.00"


def test_empty_order_rejected():
    with pytest.raises(ValueError):
        build_quote([])


def test_invalid_quantity_rejected():
    with pytest.raises(ValueError):
        LineItem("SKU-1", 0, Decimal("1.00"))


def test_parse_items():
    items = parse_items({"items": [{"sku": "A", "quantity": "2", "unit_price": 1.5}]})
    assert items == [LineItem("A", 2, Decimal("1.5"))]
