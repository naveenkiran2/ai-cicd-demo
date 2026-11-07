"""Minimal HTTP service exposing the order domain (stdlib only).

Run:  python -m app.service --port 0
Prints "READY port=<n>" once listening so automation can discover the port.
"""
import argparse
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app import SERVICE_NAME, __version__
from app.orders import build_quote, parse_items

log = logging.getLogger("order-service")


def health_payload() -> dict:
    return {"status": "ok", "service": SERVICE_NAME, "version": __version__}


def quote_handler(body: dict) -> dict:
    return build_quote(
        parse_items(body),
        discount_pct=body.get("discount_pct", 0),
        tax_rate_pct=body.get("tax_rate_pct", 0),
    )


GET_ROUTES = {"/health": health_payload}
POST_ROUTES = {"/orders/quote": quote_handler}


class Handler(BaseHTTPRequestHandler):
    server_version = f"{SERVICE_NAME}/{__version__}"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - stdlib naming
        route = GET_ROUTES.get(self.path)
        if route is None:
            self._send(404, {"error": "not found", "path": self.path})
            return
        self._send(200, route())

    def do_POST(self):  # noqa: N802 - stdlib naming
        route = POST_ROUTES.get(self.path)
        if route is None:
            self._send(404, {"error": "not found", "path": self.path})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, route(body))
        except (ValueError, KeyError) as exc:
            self._send(400, {"error": str(exc)})

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the order service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(message)s")
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    sys.stdout.write(f"READY port={httpd.server_address[1]}\n")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
