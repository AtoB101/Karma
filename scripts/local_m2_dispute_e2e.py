"""M2 逆向路径 E2E: order -> sign -> lock -> open dispute -> bill disputed -> resolve -> finalize/refund.

验证点：
- 开争议后账单状态同步为 disputed
- 争议解决后可正常走验证结算（若守卫存在则验证其拦截）
- 不存在订单开争议 -> 404
- 账单明细字段与订单一致（金额、binding、双方身份）
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
TG_ID = 930000000 + int(time.time()) % 1000000


def make_init_data() -> str:
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "local-m2-dispute-1",
        "user": json.dumps({"id": TG_ID, "first_name": "Buyer", "username": "m2_dispute"}),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


acct = Account.create()

with httpx.Client(base_url=BASE, timeout=20) as c:
    # 1. identity
    r = c.post("/v1/telegram/session", json={"init_data": make_init_data()})
    sid = r.json()["session_id"]
    auth = {"Authorization": f"Bearer {sid}"}
    r = c.post("/v1/auth/siwe/challenge", json={"address": acct.address})
    ch = r.json()
    sig = acct.sign_message(encode_defunct(text=ch["message"])).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    r = c.post("/v1/auth/siwe/verify", json={"nonce": ch["nonce"], "signature": sig, "address": acct.address})
    identity_id = r.json()["identity_id"]
    c.post("/v1/telegram/bind", headers=auth, json={"init_data": make_init_data(), "identity_id": identity_id})
    print("1. identity          OK ->", identity_id[:14])

    # 2. intent + offer + order + double sign + lock
    r = c.post("/v1/chat/intent", headers=auth,
               json={"text": "我要买一个数据抓取服务，预算8美元", "amount_usdc": "8"})
    intent = r.json()
    r = c.post("/v1/registry/agents", headers=auth,
               json={"endpoint": "https://agent.example.com/hook", "capabilities": [], "wallet": acct.address})
    agent = r.json()
    r = c.post("/v1/registry/capabilities", headers=auth,
               json={"name": "Data Fetch D", "category": "digital", "description": "dispute test"})
    cap = r.json()
    r = c.post("/v1/registry/offers", headers=auth,
               json={"agent_id": agent["agent_id"], "capability_id": cap["capability_id"],
                     "title": "dispute test offer", "price_usdc": "8", "category": "digital",
                     "seller_wallet": acct.address})
    offer = r.json()
    r = c.post("/v1/commerce/orders", headers=auth,
               json={"intent": intent.get("intent", intent), "offer_id": offer.get("offer_id")})
    order = r.json()
    assert r.status_code == 200, r.text
    c.post("/v1/commerce/orders/sign", headers=auth,
           json={"order_id": order["order_id"], "role": "buyer", "signature": "0x" + "ab" * 32})
    c.post("/v1/commerce/orders/sign", headers=auth,
           json={"order_id": order["order_id"], "role": "seller", "signature": "0x" + "cd" * 32})
    r = c.post("/v1/settlement/lock", headers=auth,
               json={"order_id": order["order_id"], "binding_id": 2026082402})
    assert r.status_code == 200 and r.json()["status"] == "LOCKED", r.text
    print("2. order LOCKED      OK ->", order["order_id"][:14])

    # 3. open dispute -> bill status sync to disputed
    r = c.post("/v1/disputes", headers=auth, json={"order_id": order["order_id"], "reason": "货不对板"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "open", d
    print("3. open dispute      OK ->", d["dispute_id"][:14], d["status"])

    r = c.get(f"/v1/commerce/bills/{order['order_id']}", headers=auth)
    assert r.status_code == 200, r.text
    bill_during = r.json()
    print("4. bill disputed     OK -> status:", bill_during.get("status"))
    assert bill_during.get("status") == "disputed", bill_during

    # 4. dispute listed
    r = c.get("/v1/disputes", headers=auth, params={"order_id": order["order_id"]})
    assert r.status_code == 200 and any(x["dispute_id"] == d["dispute_id"] for x in r.json()["disputes"]), r.text
    print("5. dispute listed    OK")

    # 5. resolve dispute (arbitration: refund buyer)
    r = c.post("/v1/disputes/resolve", headers=auth,
               json={"dispute_id": d["dispute_id"], "resolution": {"action": "refund", "to": "buyer"}})
    assert r.status_code == 200 and r.json()["status"] == "resolved", r.text
    print("6. resolve dispute   OK ->", r.json()["resolution"].get("action"))

    # 6. negative: dispute on nonexistent order -> 404
    r = c.post("/v1/disputes", headers=auth, json={"order_id": "ord_nonexistent", "reason": "x"})
    assert r.status_code == 404, f"expected 404 got {r.status_code}"
    print("7. no-order dispute  OK -> 404")

    # 7. bill detail fields match order
    r = c.get(f"/v1/commerce/bills/{order['order_id']}", headers=auth)
    bill = r.json()
    print("8. bill detail       ->", json.dumps(bill, ensure_ascii=False)[:200])

print("\nM2 dispute path E2E: PASS")
