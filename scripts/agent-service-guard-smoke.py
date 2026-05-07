#!/usr/bin/env python3
"""Smoke checks for Karma Guard single-portal frontend (index + sign-in + studio)."""

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
      portal = fetch("/apps/agent-service-guard/frontend/index.html")
      assert "KARMA//PAY" in portal
      assert "web3-login.html" in portal
      assert "studio/index.html" in portal or "studio%2Findex.html" in portal

      login = fetch("/apps/agent-service-guard/frontend/web3-login.html")
      assert "wc-config.js" in login
      assert "studio/index.html" in login

      studio = fetch("/apps/agent-service-guard/frontend/studio/index.html")
      assert "Karma Agent Studio" in studio
      assert "app.js" in studio

      print("OK   agent-service-guard smoke passed")
    finally:
      httpd.shutdown()
      httpd.server_close()


if __name__ == "__main__":
    main()
