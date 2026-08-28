"""M2 争议恢复 E2E: 开争议 -> 仲裁 release（释放给商家/继续履行）-> 账单恢复 locked ->
正常走验证 + 结算成功。验证争议解决后订单不会卡死在 disputed。
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
    bauth, _ = login(c, buyer, 981000000 + RUN, "dr-buyer-1")
    sauth, _ = login(c, seller, 991000000 + RUN, "dr-seller-1")
    print("1. dual identity     OK")

    r = c.post("/v1/registry/agents", headers=sauth,
               json={"endpoint": "https://agent.example.com/hook", "capabilities": [], "wallet": seller.address})
    agent = r.json()
    r = c.post("/v1/registry/capabilities", headers=sauth,
               json={"name": "Data Fetch DR", "category": "digital", "description": "release test"})
    cap = r.json()
    r = c.post("/v1/registry/offers", headers=sauth,
               json={"agent_id": agent["agent_id"], "capability_id": cap["capability_id"],
                     "title": "release test offer", "price_usdc": "7", "category": "digital",
                     "seller_wallet": seller.address})
    offer = r.json()

    r = c.post("/v1/commerce/orders", headers=bauth,
               json={"intent": {"scene_id": "digital", "amount_usdc": "7"}, "offer_id": offer["offer_id"]})
    order = r.json()
    c.post("/v1/commerce/orders/accept", headers=sauth, json={"order_id": order["order_id"]})
    c.post("/v1/commerce/orders/sign", headers=bauth,
           json={"order_id": order["order_id"], "role": "buyer", "signature": "0x" + "ab" * 32})
    c.post("/v1/commerce/orders/sign", headers=sauth,
           json={"order_id": order["order_id"], "role": "seller", "signature": "0x" + "cd" * 32})
    r = c.post("/v1/settlement/lock", headers=bauth,
               json={"order_id": order["order_id"], "binding_id": 2026082430})
    assert r.status_code == 200 and r.json()["status"] == "LOCKED", r.text
    print("2. order LOCKED      OK ->", order["order_id"][:14])

    # 开争议（锁定后、交付前）
    r = c.post("/v1/disputes", headers=bauth, json={"order_id": order["order_id"], "reason": "响应太慢"})
    assert r.status_code == 200, r.text
    d = r.json()
    r = c.get(f"/v1/commerce/bills/{order['order_id']}", headers=bauth)
    assert r.json()["status"] == "disputed", r.text
    print("3. open dispute      OK -> bill disputed")

    # 仲裁：争议驳回，资金继续托管，订单恢复
    r = c.post("/v1/disputes/resolve", headers=bauth,
               json={"dispute_id": d["dispute_id"], "resolution": {"action": "release", "note": "商家无责"}})
    assert r.status_code == 200 and r.json()["status"] == "resolved", r.text
    r = c.get(f"/v1/commerce/bills/{order['order_id']}", headers=bauth)
    assert r.json()["status"] == "locked", r.text
    r = c.get(f"/v1/commerce/orders/{order['order_id']}", headers=bauth)
    assert r.json()["fulfillment_status"] == "ACCEPTED", r.text
    print("4. resolve release   OK -> bill locked + fulfillment 恢复", r.json()["fulfillment_label"])

    # 继续正常履约：处理 -> 交付 -> 验收 -> 结算
    c.post("/v1/commerce/orders/start", headers=sauth, json={"order_id": order["order_id"]})
    r = c.post("/v1/commerce/orders/deliver", headers=sauth,
               json={"order_id": order["order_id"],
                     "evidence": {"delivery_receipt": "DR-DR-001", "photo_hash": "baadf00d"}})
    assert r.status_code == 200, r.text
    r = c.post("/v1/verification/runs", headers=bauth, json={"order_id": order["order_id"]})
    assert r.status_code == 200 and r.json()["status"] == "PASS", r.text
    r = c.post("/v1/settlement/finalize", headers=bauth, json={"order_id": order["order_id"]})
    assert r.status_code == 200 and r.json()["status"] == "SETTLED", r.text
    assert r.json()["fulfillment_status"] == "SETTLED", r.text
    print("5. resume + settle   OK ->", r.json()["fulfillment_label"])

print("\nM2 dispute release E2E: PASS")
