def test_quote_end_to_end(service_url, call):
    payload = {
        "items": [{"sku": "SKU-1", "quantity": 2, "unit_price": "50.00"}],
        "discount_pct": 10,
        "tax_rate_pct": 8,
    }
    status, body = call("POST", f"{service_url}/orders/quote", payload)
    assert status == 200
    assert body["total"] == "97.20"


def test_invalid_order_returns_400(service_url, call):
    status, body = call("POST", f"{service_url}/orders/quote", {"items": []})
    assert status == 400
    assert "line item" in body["error"]
