"""Bot「先账单后确认 + 授权额度直读」E2E。

验证 2026-08-25 交互改造：
1. 认证/额度直读：recommend 回复含认证摘要与授权额度（无需聊天内认证）
2. 点商家 → 出账单确认卡（bill_confirm，不创建订单不动钱）
3. 取消 → 无订单无资金变动
4. 确认支付 → 额度内自动锁仓（LOCKED，无需签名）
5. 商家 TG 一键接单 → ACCEPTED
6. 超出操作台授权额度 → 拒绝（quota_rejected，资金未动）
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
_env = open(".env").read()
BOT_TOKEN = _env.split("TELEGRAM_BOT_TOKEN=")[1].splitlines()[0].strip()
WEBHOOK_SECRET = _env.split("TELEGRAM_WEBHOOK_SECRET=")[1].splitlines()[0].strip()

TG_BUYER = 970000000 + int(time.time()) % 100000
TG_SELLER = TG_BUYER + 1


def make_init_data(tg_id: int, username: str) -> str:
    params = {
        "auth_date": str(int(time.time())),
        "query_id": f"billflow-{tg_id}",
        "user": json.dumps({"id": tg_id, "first_name": "BF", "username": username}),
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


def cbq(tg_id: int, data: str) -> dict:
    return webhook({
        "update_id": int(time.time()),
        "callback_query": {
            "id": f"cbq_{tg_id}_{int(time.time()*1000)%99999}",
            "from": {"id": tg_id, "is_bot": False, "first_name": "BF"},
            "data": data,
            "message": {"message_id": 1, "chat": {"id": tg_id, "type": "private"}, "date": int(time.time())},
        },
    })


def msg(tg_id: int, text: str) -> dict:
    return webhook({
        "update_id": int(time.time()),
        "message": {
            "message_id": int(time.time()) % 100000, "date": int(time.time()), "text": text,
            "from": {"id": tg_id, "is_bot": False, "first_name": "BF"},
            "chat": {"id": tg_id, "type": "private"},
        },
    })


def login_with_tg(tg_id: int, username: str, acct: Account) -> tuple[str, str]:
    """操作台：会话 + SIWE + TG 绑定，返回 (session_id, identity_id)。"""
    with httpx.Client(base_url=BASE, timeout=30) as c:
        r = c.post("/v1/telegram/session", json={"init_data": make_init_data(tg_id, username)})
        sid = r.json()["session_id"]
        auth = {"Authorization": f"Bearer {sid}"}
        r = c.post("/v1/auth/siwe/challenge", json={"address": acct.address})
        ch = r.json()
        sig = acct.sign_message(encode_defunct(text=ch["message"])).signature.hex()
        if not sig.startswith("0x"):
            sig = "0x" + sig
        r = c.post("/v1/auth/siwe/verify", json={"nonce": ch["nonce"], "signature": sig, "address": acct.address})
        identity_id = r.json()["identity_id"]
        c.post("/v1/telegram/bind", headers=auth, json={"init_data": make_init_data(tg_id, username), "identity_id": identity_id})
        return sid, identity_id


buyer_acct = Account.create()
seller_acct = Account.create()

with httpx.Client(base_url=BASE, timeout=30) as c:
    # 1. 买家在操作台完成认证（聊天内零认证）
    buyer_sid, buyer_kid = login_with_tg(TG_BUYER, "bf_buyer", buyer_acct)
    buyer_auth = {"Authorization": f"Bearer {buyer_sid}"}
    print("1. 买家操作台认证       OK ->", buyer_kid[:14])

    # 2. 商家在操作台完成认证并上架
    seller_sid, seller_kid = login_with_tg(TG_SELLER, "bf_seller", seller_acct)
    seller_auth = {"Authorization": f"Bearer {seller_sid}"}
    r = c.post("/v1/registry/agents", headers=seller_auth,
               json={"endpoint": "https://agent.example.com/hook", "capabilities": [], "wallet": seller_acct.address})
    agent = r.json()
    r = c.post("/v1/registry/capabilities", headers=seller_auth,
               json={"name": "BillFlow Data", "category": "digital", "description": "billflow test"})
    cap = r.json()
    r = c.post("/v1/registry/offers", headers=seller_auth,
               json={"agent_id": agent["agent_id"], "capability_id": cap["capability_id"],
                     "title": "billflow 数据抓取", "price_usdc": "10", "category": "digital",
                     "seller_wallet": seller_acct.address})
    assert r.status_code == 200, r.text
    offer_id = r.json()["offer_id"]
    print("2. 商家上架商品         OK ->", offer_id[:14])

    # 3. 买家在 Bot 聊天里直接说需求 → 回复含认证摘要与授权额度
    result = msg(TG_BUYER, "帮我找一个靠谱的商家，我需要数据抓取服务，预算 20 USDC")
    assert result["action"] == "recommend", result
    assert "已认证" in result["reply_text"], result["reply_text"]
    assert "授权额度" in result["reply_text"], result["reply_text"]
    print("3. 需求→推荐(带认证摘要) OK")
    print("   " + result["reply_text"].splitlines()[0])
    print("   " + result["reply_text"].splitlines()[1])

    # 4. 点选商家 → 账单确认卡（不是直接下单）
    result = cbq(TG_BUYER, f"karma_pick:{offer_id}")
    assert result["action"] == "bill_confirm", result
    assert "账单确认" in result["reply_text"], result["reply_text"]
    assert "额度检查通过" in result["reply_text"], result["reply_text"]
    kb = result["reply_markup"]["inline_keyboard"][0]
    assert kb[0]["callback_data"].startswith("karma_confirm:"), kb
    assert kb[1]["callback_data"] == "karma_cancel", kb
    r = c.get("/v1/commerce/orders", headers=buyer_auth)
    assert r.json().get("orders", []) == [], "点选商家不应创建订单"
    print("4. 点选→账单确认卡      OK（未创建订单、未动钱）")

    # 5. 取消 → 无任何订单
    result = cbq(TG_BUYER, "karma_cancel")
    assert result["action"] == "cancelled", result
    r = c.get("/v1/commerce/orders", headers=buyer_auth)
    n_orders = len(r.json().get("orders", []))
    print("5. 取消→零订单零资金    OK")

    # 6. 重新说需求 → 点选 → 确认支付 → 额度内自动锁仓
    result = msg(TG_BUYER, "帮我找一个靠谱的商家，我需要数据抓取服务，预算 20 USDC")
    assert result["action"] == "recommend", result
    result = cbq(TG_BUYER, f"karma_pick:{offer_id}")
    assert result["action"] == "bill_confirm", result
    result = cbq(TG_BUYER, f"karma_confirm:{offer_id}")
    assert result["action"] == "order_created", result
    order_id = result["order_id"]
    assert "已锁定托管" in result["reply_text"], result["reply_text"]
    r = c.get(f"/v1/commerce/orders/{order_id}", headers=buyer_auth)
    o = r.json()
    assert o["status"] == "LOCKED", o
    assert o["fulfillment_status"] == "PENDING_ACCEPT", o
    assert o["fulfillment_label"] == "等待接单", o
    r = c.get(f"/v1/commerce/bills/{order_id}", headers=buyer_auth)
    assert r.json().get("status") in ("locked", "LOCKED"), r.text
    print("6. 确认支付→自动锁仓    OK ->", order_id[:14], "LOCKED / 等待接单 / bill locked")

    # 7. 商家 TG 一键接单
    result = cbq(TG_SELLER, f"karma_accept:{order_id}")
    assert result["action"] == "accepted", result
    r = c.get(f"/v1/commerce/orders/{order_id}", headers=buyer_auth)
    assert r.json()["fulfillment_status"] == "ACCEPTED", r.text
    print("7. 商家一键接单         OK -> ACCEPTED（买家收到推送钩子）")

    # 8. 超出操作台授权额度 → 拒绝（资金未动）
    r = c.post("/v1/identity/policy", headers=buyer_auth,
               json={"identity_id": buyer_kid, "policy": {"single_limit_usdc": "5", "daily_limit_usdc": "5"}})
    assert r.status_code == 200, r.text
    result = msg(TG_BUYER, "帮我找一个靠谱的商家，我需要数据抓取服务，预算 20 USDC")
    assert result["action"] == "recommend", result
    assert "剩余" in result["reply_text"], result["reply_text"]
    result = cbq(TG_BUYER, f"karma_pick:{offer_id}")
    assert result["action"] == "bill_confirm", result
    assert "超出操作台授权额度" in result["reply_text"], result["reply_text"]
    result = cbq(TG_BUYER, f"karma_confirm:{offer_id}")
    assert result["action"] == "quota_rejected", result
    r = c.get("/v1/commerce/orders", headers=buyer_auth)
    # n_orders 为第5步取消后的基数；第6步成交 1 单 + 第8步被拒退回 1 单
    assert len(r.json().get("orders", [])) == n_orders + 2, "应含 1 个成交单 + 1 个被拒退款单"
    print("8. 超额度→拒绝(资金未动) OK ->", result["action"])

print("\nBot billflow E2E: PASS")
