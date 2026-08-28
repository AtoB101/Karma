"""M2 履约状态机 E2E: 下单(等待接单) -> 接单 -> 处理中 -> 交付(等待验收) -> 验收通过 -> 已结算。

负向验证：
- 买方（非卖方）尝试接单 -> 403
- 未锁定资金就 start/deliver -> 409
- 重复接单 -> 409
- 已结算订单再开争议 -> 409
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
    bauth, _ = login(c, buyer, 960000000 + RUN, "ff-buyer-1")
    sauth, seller_identity = login(c, seller, 970000000 + RUN, "ff-seller-1")
    print("1. dual identity     OK -> buyer/seller ready")

    r = c.post("/v1/registry/agents", headers=sauth,
               json={"endpoint": "https://agent.example.com/hook", "capabilities": [], "wallet": seller.address})
    agent = r.json()
    r = c.post("/v1/registry/capabilities", headers=sauth,
               json={"name": "Data Fetch FF", "category": "digital", "description": "fulfillment test"})
    cap = r.json()
    r = c.post("/v1/registry/offers", headers=sauth,
               json={"agent_id": agent["agent_id"], "capability_id": cap["capability_id"],
                     "title": "fulfillment 数据服务", "price_usdc": "15", "category": "digital",
                     "seller_wallet": seller.address})
    offer = r.json()
    print("2. seller offer      OK ->", offer.get("offer_id", "")[:14])

    r = c.post("/v1/commerce/orders", headers=bauth,
               json={"intent": {"scene_id": "digital", "amount_usdc": "15"}, "offer_id": offer["offer_id"]})
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["fulfillment_status"] == "PENDING_ACCEPT", order
    print("3. create order      OK ->", order["order_id"][:14], "|", order["fulfillment_label"])

    # 负向：买方（非卖方）接单 -> 403
    r = c.post("/v1/commerce/orders/accept", headers=bauth, json={"order_id": order["order_id"]})
    assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"
    print("4. buyer accept      BLOCKED -> 403 (only seller)")

    # 负向：未锁定就 start -> 409
    r = c.post("/v1/commerce/orders/start", headers=sauth, json={"order_id": order["order_id"]})
    assert r.status_code == 409, f"expected 409 got {r.status_code}: {r.text}"
    print("5. early start       BLOCKED -> 409 (funds not locked)")

    # 卖方接单
    r = c.post("/v1/commerce/orders/accept", headers=sauth, json={"order_id": order["order_id"]})
    assert r.status_code == 200 and r.json()["fulfillment_status"] == "ACCEPTED", r.text
    print("6. seller accept     OK ->", r.json()["fulfillment_label"])

    # 负向：重复接单 -> 409
    r = c.post("/v1/commerce/orders/accept", headers=sauth, json={"order_id": order["order_id"]})
    assert r.status_code == 409, f"expected 409 got {r.status_code}: {r.text}"
    print("7. double accept     BLOCKED -> 409")

    # 签名 + 锁定
    c.post("/v1/commerce/orders/sign", headers=bauth,
           json={"order_id": order["order_id"], "role": "buyer", "signature": "0x" + "ab" * 32})
    c.post("/v1/commerce/orders/sign", headers=sauth,
           json={"order_id": order["order_id"], "role": "seller", "signature": "0x" + "cd" * 32})
    r = c.post("/v1/settlement/lock", headers=bauth,
               json={"order_id": order["order_id"], "binding_id": 2026082410})
    assert r.status_code == 200 and r.json()["status"] == "LOCKED", r.text
    print("8. sign + lock       OK -> LOCKED")

    # 开始处理
    r = c.post("/v1/commerce/orders/start", headers=sauth, json={"order_id": order["order_id"]})
    assert r.status_code == 200 and r.json()["fulfillment_status"] == "PROCESSING", r.text
    print("9. start processing  OK ->", r.json()["fulfillment_label"])

    # 负向：未接单就交付（新订单）
    r = c.post("/v1/commerce/orders", headers=bauth,
               json={"intent": {"scene_id": "digital", "amount_usdc": "15"}, "offer_id": offer["offer_id"]})
    order2 = r.json()
    r = c.post("/v1/commerce/orders/deliver", headers=sauth,
               json={"order_id": order2["order_id"], "evidence": {"x": "1"}})
    assert r.status_code == 409, f"expected 409 got {r.status_code}: {r.text}"
    print("10. deliver w/o lock BLOCKED -> 409")

    # 交付（提交证据）
    r = c.post("/v1/commerce/orders/deliver", headers=sauth,
               json={"order_id": order["order_id"],
                     "evidence": {"delivery_receipt": "DR-FF-001", "photo_hash": "cafebabe"}})
    assert r.status_code == 200 and r.json()["status"] == "EVIDENCE_SUBMITTED", r.text
    assert r.json()["fulfillment_status"] == "DELIVERED", r.text
    print("11. deliver          OK ->", r.json()["fulfillment_label"])

    # 验证（验收）
    r = c.post("/v1/verification/runs", headers=bauth, json={"order_id": order["order_id"]})
    assert r.status_code == 200 and r.json()["status"] == "PASS", r.text
    r = c.get(f"/v1/commerce/orders/{order['order_id']}", headers=bauth)
    assert r.json()["fulfillment_status"] == "VERIFIED", r.text
    print("12. verify (验收)    OK ->", r.json()["fulfillment_label"])

    # 结算
    r = c.post("/v1/settlement/finalize", headers=bauth, json={"order_id": order["order_id"]})
    assert r.status_code == 200 and r.json()["status"] == "SETTLED", r.text
    assert r.json()["fulfillment_status"] == "SETTLED", r.text
    print("13. finalize         OK ->", r.json()["fulfillment_label"])

    # 负向：已结算订单开争议 -> 409
    r = c.post("/v1/disputes", headers=bauth, json={"order_id": order["order_id"], "reason": "事后反悔"})
    assert r.status_code == 409, f"expected 409 got {r.status_code}: {r.text}"
    print("14. dispute settled  BLOCKED -> 409")

print("\nM2 fulfillment E2E: PASS")
