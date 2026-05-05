#!/usr/bin/env python3
"""Minimal smoke checks for Karma Guard public frontend pages."""

from __future__ import annotations

import http.server
import socketserver
import threading
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"


def fetch(path: str) -> str:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Unexpected HTTP status for {path}: {resp.status}")
        return resp.read().decode("utf-8", errors="replace")


def main() -> None:
    handler = http.server.SimpleHTTPRequestHandler
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    httpd.allow_reuse_address = True

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)

    try:
      index = fetch("/apps/agent-service-guard/frontend/index.html")
      assert "Karma Guard for Agent Services" in index
      assert "Create Protected Service" in index
      assert "Pay with Protection" in index

      create_page = fetch("/apps/agent-service-guard/frontend/service-create.html")
      assert "seller_bond_rate" in create_page

      pay_page = fetch("/apps/agent-service-guard/frontend/pay.html")
      assert "Pay with Protection" in pay_page

      order_page = fetch("/apps/agent-service-guard/frontend/order.html")
      assert "Admin Mock Arbitration" in order_page

      dashboard_page = fetch("/apps/agent-service-guard/frontend/dashboard.html")
      assert "Karma Guard Dashboard" in dashboard_page

      badge_page = fetch("/apps/agent-service-guard/frontend/badge.html")
      assert "Karma Protected Badge" in badge_page

      print("OK   agent-service-guard smoke passed")
    finally:
      httpd.shutdown()
      httpd.server_close()


if __name__ == "__main__":
    main()
