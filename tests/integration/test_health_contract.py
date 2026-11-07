"""Contract: the health payload consumed by the platform's monitoring."""

REQUIRED_FIELDS = {"status", "service", "version"}


def test_health_contract_fields(service_url, call):
    status, body = call("GET", f"{service_url}/health")
    assert status == 200
    assert REQUIRED_FIELDS <= body.keys()
    assert body["status"] == "ok"


def test_unknown_route_returns_404(service_url, call):
    status, _ = call("GET", f"{service_url}/does-not-exist")
    assert status == 404
