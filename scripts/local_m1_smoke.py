"""Local M1 smoke test: forge valid initData with the real bot token, then call
MiniApp endpoints: /telegram/session -> /telegram/me -> /identity/nonce."""
import hashlib
import hmac
import json
import time
import urllib.parse

import httpx

BASE = "http://127.0.0.1:8000"
BOT_TOKEN = open(".env").read().split("TELEGRAM_BOT_TOKEN=")[1].splitlines()[0].strip()

params = {
    "auth_date": str(int(time.time())),
    "query_id": "local-smoke-1",
    "user": json.dumps({
        "id": 900000001,
        "first_name": "Smoke",
        "last_name": "Tester",
        "username": "smoke_tester",
        "language_code": "en",
    }),
}
check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
params["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
init_data = urllib.parse.urlencode(params)

with httpx.Client(base_url=BASE, timeout=15) as c:
    r = c.post("/v1/telegram/session", json={"init_data": init_data})
    print("POST /telegram/session ->", r.status_code, r.json() if r.status_code < 400 else r.text)
    sid = r.json().get("session_id")

    r2 = c.get("/v1/telegram/me", headers={"Authorization": f"Bearer {sid}"})
    print("GET  /telegram/me     ->", r2.status_code, r2.json() if r2.status_code < 400 else r2.text)

    r3 = c.get("/v1/identity/nonce", headers={"Authorization": f"Bearer {sid}"})
    print("GET  /identity/nonce  ->", r3.status_code, r3.json() if r3.status_code < 400 else r3.text[:200])

    # security check: policy endpoint should now reject unauthenticated access
    r4 = c.post("/v1/identity/policy", json={})
    print("POST /identity/policy (no auth) ->", r4.status_code, "(expect 401)")
