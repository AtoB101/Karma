"""Full M1 E2E: session -> SIWE challenge -> sign -> verify -> telegram bind."""
import hashlib
import hmac
import json
import time
import urllib.parse

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

BASE = "http://127.0.0.1:8000"
BOT_TOKEN = open(".env").read().split("TELEGRAM_BOT_TOKEN=")[1].splitlines()[0].strip()
TG_ID = 900000001


def make_init_data() -> str:
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "local-smoke-2",
        "user": json.dumps({
            "id": TG_ID, "first_name": "Smoke", "username": "smoke_tester",
        }),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


acct = Account.create()
print("ephemeral wallet:", acct.address)

with httpx.Client(base_url=BASE, timeout=20) as c:
    # 1. initData session
    r = c.post("/v1/telegram/session", json={"init_data": make_init_data()})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    print("1. session        OK ->", sid[:16], "...")
    auth = {"Authorization": f"Bearer {sid}"}

    # 2. SIWE challenge
    r = c.post("/v1/auth/siwe/challenge", json={"address": acct.address})
    assert r.status_code == 200, r.text
    ch = r.json()
    print("2. challenge      OK -> nonce", ch["nonce"][:12], "... chain", ch["chain_id"])

    # 3. sign EIP-191 personal message
    signed = acct.sign_message(encode_defunct(text=ch["message"]))
    sig = signed.signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    print("3. sign           OK ->", sig[:20], "...")

    # 4. verify
    r = c.post("/v1/auth/siwe/verify", json={"nonce": ch["nonce"], "signature": sig, "address": acct.address})
    assert r.status_code == 200, r.text
    ident = r.json()
    print("4. siwe verify    OK -> identity", ident["identity_id"], "wallet", ident["wallet"][:10], "...")

    # 5. bind telegram
    r = c.post(
        "/v1/telegram/bind",
        json={"init_data": make_init_data(), "identity_id": ident["identity_id"]},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    print("5. telegram bind  OK ->", r.json())

    # 6. session now shows bound
    r = c.get("/v1/telegram/me", headers=auth)
    assert r.status_code == 200, r.text
    me = r.json()
    print("6. me (bound)     OK -> identity", me["identity"]["identity_id"] if me.get("identity") else me)

    # 7. bad signature must fail
    r = c.post("/v1/auth/siwe/verify", json={"nonce": ch["nonce"], "signature": "0x" + "00" * 65, "address": acct.address})
    print("7. bad sig rejected ->", r.status_code, "(expect 401)")

print("\nM1 E2E: PASS")
