#!/usr/bin/env python3
"""
Minimal local receiver for Karma OpenClaw outbound webhooks.

  export OPENCLAW_WEBHOOK_SECRET=same-as-KARMA-openclaw-webhook-secret
  python3 scripts/openclaw_webhook_receiver.py --port 8765

On the Karma API host:

  export OPENCLAW_WEBHOOK_URL=http://127.0.0.1:8765/hook
  export OPENCLAW_WEBHOOK_SECRET=...
  export OPENCLAW_WEBHOOK_STORE_EVENTS=true   # optional poll fallback via /v1/openclaw/handoff-events
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer


def _verify(sig_header: str | None, body: bytes, secret: str) -> bool:
    if not secret:
        return True
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig_header, f"sha256={expected}")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/hook":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        secret = os.environ.get("OPENCLAW_WEBHOOK_SECRET", "").strip()
        if not _verify(self.headers.get("X-Karma-Signature"), body, secret):
            self.send_response(401)
            self.end_headers()
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}\n')

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    srv = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"listening on http://127.0.0.1:{args.port}/hook")
    srv.serve_forever()


if __name__ == "__main__":
    main()
