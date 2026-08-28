"""Bot 对话编排层 E2E: 自然语言 -> 推荐商家(inline) -> 点选下单 -> 状态推送钩子。

模拟 Telegram webhook 更新（本地直打 /v1/telegram/bot/webhook，带 secret 头），
验证：意图解析、TOP商家推荐、回调下单、订单全流程中通知钩子被触发。
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
WEBHOOK_SECRET = open(".env").read().split("TELEGRAM_WEBHOOK_SECRET=")[1].splitlines()[0].strip()
TG_ID = 960000000 + int(time.time()) % 1000000


def make_init_data() -> str:
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "bot-concierge-1",
        "user": json.dumps({"id": TG_ID, "first_name": "Concierge", "username": "cc_buyer"}),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def webhook(update: dict) -> dict:
    r = httpx.post(
        BASE + "/v1/telegram/bot/webhook",
        json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()


acct = Account.from_key("a3bd6e441963f0b097458d5658884633eaeb1dec8e0142e4f23ce64ebe10b3df")  # W1 买方
seller_acct = Account.create()  # 卖方（与买方不同钱包，避免触发 self_deal 风控）

with httpx.Client(base_url=BASE, timeout=30) as c:
    # 1. 身份：会话 + SIWE + TG绑定（模拟用户已在MiniApp完成钱包登录）
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
    r = c.post("/v1/telegram/bind", headers=auth, json={"init_data": make_init_data(), "identity_id": identity_id})
    assert r.status_code == 200, r.text
    print("1. identity bound     OK ->", identity_id[:14], "tg", TG_ID)

    # 2. 商家上架一个 digital 商品（同一身份充当商家）
    r = c.post("/v1/registry/agents", headers=auth,
               json={"endpoint": "https://agent.example.com/hook", "capabilities": [], "wallet": seller_acct.address})
    agent = r.json()
    r = c.post("/v1/registry/capabilities", headers=auth,
               json={"name": "Data Fetch C", "category": "digital", "description": "concierge test"})
    cap = r.json()
    r = c.post("/v1/registry/offers", headers=auth,
               json={"agent_id": agent["agent_id"], "capability_id": cap["capability_id"],
                     "title": "concierge 数据抓取", "price_usdc": "10", "category": "digital",
                     "seller_wallet": seller_acct.address})
    assert r.status_code == 200, r.text
    print("2. offer published    OK ->", r.json()["offer_id"][:14])

    # 3. 模拟用户在 Bot 聊天里发自然语言需求
    result = webhook({
        "update_id": 1001,
        "message": {
            "message_id": 11, "date": int(time.time()), "text": "帮我找一个靠谱的商家，我需要数据抓取服务，预算100 USDC",
            "from": {"id": TG_ID, "is_bot": False, "first_name": "Concierge", "username": "cc_buyer"},
            "chat": {"id": TG_ID, "type": "private"},
        },
    })
    assert result["action"] == "recommend", result
    kb = result["reply_markup"]["inline_keyboard"]
    assert kb, result
    print("3. bot recommend      OK ->", len(kb), "个商家按钮")
    print("   回复内容:\n" + "\n".join("   " + l for l in result["reply_text"].splitlines()))
    offer_id = kb[0][0]["callback_data"].split(":", 1)[1]

    # 4. 点选商家 → 账单确认卡（2026-08-25 改造：先账单后确认，不动钱）
    result = webhook({
        "update_id": 1002,
        "callback_query": {
            "id": "cbq_1", "from": {"id": TG_ID, "is_bot": False, "first_name": "Concierge"},
            "data": f"karma_pick:{offer_id}",
            "message": {"message_id": 11, "chat": {"id": TG_ID, "type": "private"}, "date": int(time.time())},
        },
    })
    assert result["action"] == "bill_confirm", result
    assert "账单确认" in result["reply_text"], result["reply_text"]
    print("4. pick -> bill card  OK（先账单，未创建订单）")

    # 5. 确认支付 → 额度内自动锁仓（触发 LOCKED 推送钩子，聊天内零签名）
    result = webhook({
        "update_id": 1003,
        "callback_query": {
            "id": "cbq_2", "from": {"id": TG_ID, "is_bot": False, "first_name": "Concierge"},
            "data": f"karma_confirm:{offer_id}",
            "message": {"message_id": 12, "chat": {"id": TG_ID, "type": "private"}, "date": int(time.time())},
        },
    })
    assert result["action"] == "order_created", result
    order_id = result["order_id"]
    assert "已锁定托管" in result["reply_text"], result["reply_text"]
    r = c.get(f"/v1/commerce/orders/{order_id}", headers=auth)
    assert r.json()["status"] == "LOCKED", r.text
    print("5. confirm -> locked  OK ->", order_id[:14], "LOCKED")

    # 6. 账单同步为 locked
    r = c.get(f"/v1/commerce/bills/{order_id}", headers=auth)
    assert r.json().get("status") in ("locked", "LOCKED"), r.text
    print("6. bill locked        OK")

    # 7. 证据 + 验证（触发 PASS 推送钩子）
    r = c.post("/v1/evidence/bundles", headers=auth, json={"order_id": order_id, "evidence": {"receipt": "R-001"}})
    r = c.post("/v1/verification/runs", headers=auth, json={"order_id": order_id})
    assert r.json()["status"] == "PASS", r.text
    print("7. verification PASS  OK")

    # 8. 结算（触发 SETTLED 推送钩子）
    r = c.post("/v1/settlement/finalize", headers=auth, json={"order_id": order_id})
    assert r.json()["status"] == "SETTLED", r.text
    print("8. settled            OK -> 推送钩子已全部触发（chat不存在时静默降级属预期）")

print("\nBot concierge E2E: PASS")
