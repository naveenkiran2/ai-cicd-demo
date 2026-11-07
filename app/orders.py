"""Order domain logic: validate line items and build a priced quote."""
from dataclasses import dataclass
from decimal import Decimal

from app.pricing import calculate_total, to_money


@dataclass(frozen=True)
class LineItem:
    sku: str
    quantity: int
    unit_price: Decimal

    def __post_init__(self):
        if not self.sku:
            raise ValueError("sku is required")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if Decimal(str(self.unit_price)) < 0:
            raise ValueError("unit_price must be >= 0")

    @property
    def line_total(self) -> Decimal:
        return to_money(Decimal(str(self.unit_price)) * self.quantity)


def build_quote(items, discount_pct=0, tax_rate_pct=0) -> dict:
    """Return a JSON-serialisable quote for a list of LineItem objects."""
    if not items:
        raise ValueError("an order needs at least one line item")
    subtotal = sum((item.line_total for item in items), Decimal("0"))
    priced = calculate_total(subtotal, discount_pct, tax_rate_pct)
    return {
        "items": [
            {"sku": i.sku, "quantity": i.quantity, "line_total": str(i.line_total)}
            for i in items
        ],
        **{key: str(value) for key, value in priced.items()},
        "currency": "USD",
    }


def parse_items(payload) -> list:
    """Build LineItem objects from a request payload."""
    return [
        LineItem(sku=row["sku"], quantity=int(row["quantity"]), unit_price=Decimal(str(row["unit_price"])))
        for row in payload.get("items", [])
    ]
