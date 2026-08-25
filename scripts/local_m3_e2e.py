"""M3 E2E: session -> SIWE identity -> telegram bind -> business -> capability -> agent -> offer -> lists."""
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
TG_ID = 900000000 + int(time.time()) % 1000000


def make_init_data(tg_id: int | None = None) -> str:
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "local-m3-smoke-1",
        "user": json.dumps({
            "id": tg_id or TG_ID, "first_name": "Merchant", "username": "m3_merchant",
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
    print("1. session           OK ->", sid[:16], "...")
    auth = {"Authorization": f"Bearer {sid}"}

    # 2-4. SIWE identity (challenge -> sign -> verify)
    r = c.post("/v1/auth/siwe/challenge", json={"address": acct.address})
    assert r.status_code == 200, r.text
    ch = r.json()
    sig = acct.sign_message(encode_defunct(text=ch["message"])).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    r = c.post("/v1/auth/siwe/verify", json={"nonce": ch["nonce"], "signature": sig, "address": acct.address})
    assert r.status_code == 200, r.text
    identity_id = r.json()["identity_id"]
    print("2. siwe identity     OK ->", identity_id[:14], "...")

    # 5. telegram bind (with session bearer so identity binds INTO the session)
    r = c.post("/v1/telegram/bind", headers=auth,
               json={"init_data": make_init_data(), "identity_id": identity_id})
    assert r.status_code == 200, r.text
    print("3. telegram bind     OK ->", r.json()["telegram_user_id"])

    # 6. register business
    r = c.post("/v1/registry/businesses", headers=auth,
               json={"legal_name": "Karma Coffee Lab", "country": "SG",
                     "metadata": {"website": "https://example.com"}})
    assert r.status_code == 200, r.text
    biz = r.json()
    print("4. register business OK ->", biz["business_id"][:14], "... level", biz["verification_level"])

    # 7. verify business (self-attest upgrade)
    r = c.post(f"/v1/registry/businesses/{biz['business_id']}/verify", headers=auth)
    assert r.status_code == 200, r.text
    print("5. verify business   OK -> level", r.json().get("verification_level"))

    # 8. publish capability
    r = c.post("/v1/registry/capabilities", headers=auth,
               json={"name": "AI Delivery Routing", "category": "logistics",
                     "description": "Route parcels with AI agents", "sla": {"p95_ms": 800}})
    assert r.status_code == 200, r.text
    cap = r.json()
    print("6. capability        OK ->", cap.get("capability_id", cap)[:14])

    # 9. register agent
    r = c.post("/v1/registry/agents", headers=auth,
               json={"endpoint": "https://agent.example.com/webhook",
                     "capabilities": [cap.get("capability_id", cap)],
                     "business_id": biz["business_id"], "wallet": acct.address})
    assert r.status_code == 200, r.text
    agent = r.json()
    print("7. register agent    OK ->", str(agent.get("agent_id", agent))[:14])

    # 10. create offer
    r = c.post("/v1/registry/offers", headers=auth,
               json={"agent_id": agent["agent_id"], "capability_id": cap["capability_id"],
                     "title": "Same-day delivery in SG", "price_usdc": "12.50",
                     "category": "logistics", "seller_wallet": acct.address})
    assert r.status_code == 200, r.text
    offer = r.json()
    print("8. create offer      OK ->", str(offer.get("offer_id", offer))[:14])

    # 11. lists visible
    r = c.get("/v1/registry/businesses", headers=auth)
    assert r.status_code == 200 and any(b["business_id"] == biz["business_id"] for b in r.json()["businesses"]), r.text
    print("9. list businesses   OK -> total", len(r.json()["businesses"]))

    r = c.get("/v1/registry/offers", headers=auth)
    assert r.status_code == 200, r.text
    items = r.json()["offers"]
    assert any(o.get("offer_id") == offer.get("offer_id") for o in items), items
    print("10. list offers      OK -> total", len(items))

    # 12. unauthenticated access rejected (security)
    r = c.post("/v1/registry/businesses", json={"legal_name": "X"})
    assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"
    print("11. no-auth rejected OK ->", r.status_code)

    # 13. bind-required guard: fresh session for a NEW user (no identity) cannot register
    fresh_tg = TG_ID + 7
    r2 = c.post("/v1/telegram/session", json={"init_data": make_init_data(tg_id=fresh_tg)})
    sid2 = r2.json()["session_id"]
    r = c.post("/v1/registry/businesses", headers={"Authorization": f"Bearer {sid2}"},
               json={"legal_name": "Y"})
    assert r.status_code == 400, f"expected 400 got {r.status_code}"
    print("12. no-identity guard OK ->", r.status_code)

print("\nM3 E2E: PASS")
