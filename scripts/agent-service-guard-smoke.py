#!/usr/bin/env python3
"""Minimal smoke checks for Karma Guard public frontend pages."""

from __future__ import annotations

import http.server
import socketserver
import threading
import time
import urllib.request
import socket
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"


def reserve_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def fetch(path: str) -> str:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Unexpected HTTP status for {path}: {resp.status}")
        return resp.read().decode("utf-8", errors="replace")


def main() -> None:
    global PORT, BASE
    PORT = reserve_port()
    BASE = f"http://127.0.0.1:{PORT}"
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
      assert "service_id is required" in pay_page

      order_page = fetch("/apps/agent-service-guard/frontend/order.html")
      assert "order_id is required" in order_page

      dashboard_page = fetch("/apps/agent-service-guard/frontend/dashboard.html")
      assert "Karma Guard Dashboard" in dashboard_page

      badge_page = fetch("/apps/agent-service-guard/frontend/badge.html")
      assert "Karma Protected Badge" in badge_page

      studio_page = fetch("/apps/agent-service-guard/frontend/studio/index.html")
      assert "Karma Agent Studio" in studio_page
      assert "app.js" in studio_page

      gateway_page = fetch("/apps/agent-service-guard/frontend/site/gateway.html")
      assert "KarmaPay — Gateway" in gateway_page
      assert "Audience routing" in gateway_page
      assert "professional.html" in gateway_page

      professional = fetch("/apps/agent-service-guard/frontend/site/professional.html")
      assert "Keep funds in user wallets" in professional
      assert "site-lang.js" in professional

      loyal = fetch("/apps/agent-service-guard/frontend/site/loyal.html")
      assert "Loyal view" in loyal
      assert "Community" in loyal

      builder_page = fetch("/apps/agent-service-guard/frontend/site/builder.html")
      assert "KarmaPay Builder Mode" in builder_page
      assert "Deploy your own settlement layer" in builder_page

      clean_redirect = fetch("/apps/agent-service-guard/frontend/site/index-clean.html")
      assert "professional.html" in clean_redirect

      war_redirect = fetch("/apps/agent-service-guard/frontend/site/war.html")
      assert "loyal.html" in war_redirect

      web3_login_page = fetch("/apps/agent-service-guard/frontend/site/web3-login.html")
      assert "qr-box" in web3_login_page
      assert "wc-project-id" in web3_login_page
      assert "word-grid" in web3_login_page
      assert "site-lang.js" in web3_login_page

      print("OK   agent-service-guard smoke passed")
    finally:
      httpd.shutdown()
      httpd.server_close()


if __name__ == "__main__":
    main()
