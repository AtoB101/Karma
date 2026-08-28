"""M2 E2E: intent -> discovery -> order -> sign -> lock -> evidence -> verify -> settle -> bill -> reputation.

链上交互（Bilateral.lock/settle）由 relayer 外部提交，API 层只做状态机编排，
因此本测试无需 Sepolia ETH。
"""
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
TG_ID = 910000000 + int(time.time()) % 1000000


def make_init_data() -> str:
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "local-m2-smoke-1",
        "user": json.dumps({
            "id": TG_ID, "first_name": "Buyer", "username": "m2_buyer",
        }),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


acct = Account.create()
print("ephemeral wallet:", acct.address)

with httpx.Client(base_url=BASE, timeout=20) as c:
    # 1. identity (session + SIWE + bind)
    r = c.post("/v1/telegram/session", json={"init_data": make_init_data()})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    auth = {"Authorization": f"Bearer {sid}"}

    r = c.post("/v1/auth/siwe/challenge", json={"address": acct.address})
    ch = r.json()
    sig = acct.sign_message(encode_defunct(text=ch["message"])).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    r = c.post("/v1/auth/siwe/verify", json={"nonce": ch["nonce"], "signature": sig, "address": acct.address})
    identity_id = r.json()["identity_id"]
    r = c.post("/v1/telegram/bind", headers=auth,
               json={"init_data": make_init_data(), "identity_id": identity_id})
    assert r.status_code == 200, r.text
    print("1. identity          OK ->", identity_id[:14])

    # 2. chat intent (natural language -> structured intent)
    r = c.post("/v1/chat/intent", headers=auth,
               json={"text": "我要买一个数据抓取服务，预算12美元", "amount_usdc": "12"})
    assert r.status_code == 200, r.text
    intent = r.json()
    print("2. chat intent       OK -> scene", intent["intent"]["scene_id"], "amount", intent["intent"]["amount_usdc"])

    # 2b. publish a matching offer (registry is in-memory per process; seed via API)
    r = c.post("/v1/registry/agents", headers=auth,
               json={"endpoint": "https://agent.example.com/hook", "capabilities": [], "wallet": acct.address})
    agent = r.json()
    r = c.post("/v1/registry/capabilities", headers=auth,
               json={"name": "Data Fetch", "category": "digital", "description": "API data fetch agent"})
    cap = r.json()
    r = c.post("/v1/registry/offers", headers=auth,
               json={"agent_id": agent["agent_id"], "capability_id": cap["capability_id"],
                     "title": "API data fetch agent", "price_usdc": "10", "category": "digital",
                     "seller_wallet": acct.address})
    assert r.status_code == 200, r.text
    print("2b. publish offer    OK ->", r.json()["offer_id"][:14])

    # 3. discovery offers
    r = c.get("/v1/discovery/offers", headers=auth)
    assert r.status_code == 200, r.text
    offers = r.json().get("offers") or r.json().get("items") or []
    assert offers, r.text
    offer = offers[0]
    print("3. discovery offers  OK -> total", len(offers), "first:", offer.get("title", "")[:30])

    # 4. create order with offer
    r = c.post("/v1/commerce/orders", headers=auth,
               json={"intent": intent.get("intent", intent), "offer_id": offer.get("offer_id")})
    assert r.status_code == 200, r.text
    order = r.json()
    print("4. create order      OK ->", order["order_id"][:14], "status", order["status"], "amount", order.get("amount_usdc"))

    # 5. sign order (both buyer + seller -> SIGNED)
    r = c.post("/v1/commerce/orders/sign", headers=auth,
               json={"order_id": order["order_id"], "role": "buyer", "signature": "0x" + "ab" * 32})
    assert r.status_code == 200, r.text
    r = c.post("/v1/commerce/orders/sign", headers=auth,
               json={"order_id": order["order_id"], "role": "seller", "signature": "0x" + "cd" * 32})
    assert r.status_code == 200, r.text
    print("5. sign order        OK -> status", r.json()["status"])

    # 6. settlement lock (relayer submits chain tx out of band)
    r = c.post("/v1/settlement/lock", headers=auth,
               json={"order_id": order["order_id"], "binding_id": 2026082401})
    assert r.status_code == 200, r.text
    print("6. lock              OK -> status", r.json()["status"], "binding", r.json().get("binding_id"))

    # 7. submit evidence
    r = c.post("/v1/evidence/bundles", headers=auth,
               json={"order_id": order["order_id"],
                     "evidence": {"delivery_receipt": "DR-2024-001", "photo_hash": "deadbeef"}})
    assert r.status_code == 200, r.text
    print("7. evidence          OK ->", len(r.json().get("evidence") or {}), "items")

    # 8. verification run (must PASS)
    r = c.post("/v1/verification/runs", headers=auth, json={"order_id": order["order_id"]})
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "PASS", run
    print("8. verification      OK ->", run["status"], "settle_allowed:", run["settle_allowed"], "risk:", run["risk"]["score"])

    # 9. settlement finalize
    r = c.post("/v1/settlement/finalize", headers=auth, json={"order_id": order["order_id"]})
    assert r.status_code == 200, r.text
    fin = r.json()
    print("9. finalize          OK -> status", fin["status"], "exec_record", fin.get("execution_record_id", "")[:14])

    # 10. bill
    r = c.get(f"/v1/commerce/bills/{order['order_id']}", headers=auth)
    assert r.status_code == 200, r.text
    print("10. bill             OK -> status", r.json().get("status"))

    # 11. reputation recorded (rate limit 30/60s: full flow + prior runs exhausted the window)
    time.sleep(61)
    r = c.get(f"/v1/miniapp/reputation/{identity_id}", headers=auth)
    assert r.status_code == 200, r.text
    print("11. reputation       OK ->", json.dumps(r.json(), ensure_ascii=False)[:80])

    # 12. negative: finalize before verification on a second order -> 403
    r = c.post("/v1/commerce/orders", headers=auth,
               json={"intent": intent.get("intent", intent), "offer_id": offer.get("offer_id")})
    order2 = r.json()
    r = c.post("/v1/settlement/finalize", headers=auth, json={"order_id": order2["order_id"]})
    assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"
    print("12. early-finalize blocked OK -> 403")

print("\nM2 E2E: PASS")
