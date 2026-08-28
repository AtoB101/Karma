"""M2 争议守卫 E2E（缺陷修复验证）:
- 开争议后 finalize 必须被 403 拦截（open dispute blocks settle）
- 仲裁 refund 后：订单 REFUNDED + 账单 refunded（状态回写修复）
- refund 后再 finalize -> 409（非 VERIFIED 状态不可结算）
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
RUN = int(time.time()) % 100000


def make_init_data(tg_id: int, query_id: str) -> str:
    params = {
        "auth_date": str(int(time.time())),
        "query_id": query_id,
        "user": json.dumps({"id": tg_id, "first_name": "U", "username": f"u_{tg_id % 100000}"}),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def login(c: httpx.Client, acct, tg_id: int, query_id: str):
    r = c.post("/v1/telegram/session", json={"init_data": make_init_data(tg_id, query_id)})
    assert r.status_code == 200, r.text
    auth = {"Authorization": "Bearer " + r.json()["session_id"]}
    r = c.post("/v1/auth/siwe/challenge", json={"address": acct.address})
    ch = r.json()
    sig = acct.sign_message(encode_defunct(text=ch["message"])).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    r = c.post("/v1/auth/siwe/verify", json={"nonce": ch["nonce"], "signature": sig, "address": acct.address})
    identity_id = r.json()["identity_id"]
    c.post("/v1/telegram/bind", headers=auth,
           json={"init_data": make_init_data(tg_id, query_id), "identity_id": identity_id})
    return auth, identity_id


buyer = Account.create()
seller = Account.create()

with httpx.Client(base_url=BASE, timeout=20) as c:
    bauth, _ = login(c, buyer, 980000000 + RUN, "dg-buyer-1")
    sauth, _ = login(c, seller, 990000000 + RUN, "dg-seller-1")
    print("1. dual identity     OK")

    r = c.post("/v1/registry/agents", headers=sauth,
               json={"endpoint": "https://agent.example.com/hook", "capabilities": [], "wallet": seller.address})
    agent = r.json()
    r = c.post("/v1/registry/capabilities", headers=sauth,
               json={"name": "Data Fetch DG", "category": "digital", "description": "guard test"})
    cap = r.json()
    r = c.post("/v1/registry/offers", headers=sauth,
               json={"agent_id": agent["agent_id"], "capability_id": cap["capability_id"],
                     "title": "guard test offer", "price_usdc": "9", "category": "digital",
                     "seller_wallet": seller.address})
    offer = r.json()
    print("2. seller offer      OK")

    r = c.post("/v1/commerce/orders", headers=bauth,
               json={"intent": {"scene_id": "digital", "amount_usdc": "9"}, "offer_id": offer["offer_id"]})
    order = r.json()
    c.post("/v1/commerce/orders/accept", headers=sauth, json={"order_id": order["order_id"]})
    c.post("/v1/commerce/orders/sign", headers=bauth,
           json={"order_id": order["order_id"], "role": "buyer", "signature": "0x" + "ab" * 32})
    c.post("/v1/commerce/orders/sign", headers=sauth,
           json={"order_id": order["order_id"], "role": "seller", "signature": "0x" + "cd" * 32})
    r = c.post("/v1/settlement/lock", headers=bauth,
               json={"order_id": order["order_id"], "binding_id": 2026082420})
    assert r.status_code == 200 and r.json()["status"] == "LOCKED", r.text
    print("3. order LOCKED      OK ->", order["order_id"][:14])

    # 交付证据 + 验证 PASS（先满足结算的全部前置，只剩争议）
    c.post("/v1/commerce/orders/start", headers=sauth, json={"order_id": order["order_id"]})
    r = c.post("/v1/commerce/orders/deliver", headers=sauth,
               json={"order_id": order["order_id"],
                     "evidence": {"delivery_receipt": "DR-DG-001", "photo_hash": "feedface"}})
    assert r.status_code == 200, r.text
    r = c.post("/v1/verification/runs", headers=bauth, json={"order_id": order["order_id"]})
    assert r.status_code == 200 and r.json()["status"] == "PASS", r.text
    print("4. delivered+PASS    OK (验收通过，具备结算条件)")

    # 开争议
    r = c.post("/v1/disputes", headers=bauth, json={"order_id": order["order_id"], "reason": "数据质量差"})
    assert r.status_code == 200, r.text
    d = r.json()
    r = c.get(f"/v1/commerce/orders/{order['order_id']}", headers=bauth)
    assert r.json()["fulfillment_status"] == "DISPUTED", r.text
    print("5. open dispute      OK ->", d["dispute_id"][:14], "| fulfillment:", r.json()["fulfillment_label"])

    # 核心：验证已 PASS、无风险 hold，但存在 open dispute -> finalize 必须被拦
    r = c.post("/v1/settlement/finalize", headers=bauth, json={"order_id": order["order_id"]})
    assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"
    print("6. settle w/ dispute BLOCKED -> 403 (缺陷修复生效)")

    # 仲裁退款
    r = c.post("/v1/disputes/resolve", headers=bauth,
               json={"dispute_id": d["dispute_id"], "resolution": {"action": "refund", "to": "buyer"}})
    assert r.status_code == 200 and r.json()["status"] == "resolved", r.text
    r = c.get(f"/v1/commerce/orders/{order['order_id']}", headers=bauth)
    o = r.json()
    assert o["status"] == "REFUNDED" and o["fulfillment_status"] == "REFUNDED", o
    r = c.get(f"/v1/commerce/bills/{order['order_id']}", headers=bauth)
    assert r.status_code == 200 and r.json()["status"] == "refunded", r.text
    print("7. resolve refund    OK -> order REFUNDED + bill refunded (回写修复生效)")

    # 退款后再结算 -> 409
    r = c.post("/v1/settlement/finalize", headers=bauth, json={"order_id": order["order_id"]})
    assert r.status_code in (403, 409), f"expected 403/409 got {r.status_code}: {r.text}"
    print("8. settle refunded   BLOCKED ->", r.status_code)

print("\nM2 dispute guard E2E: PASS")
