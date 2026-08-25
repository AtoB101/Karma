"""Bot 7 项菜单 + 子身份回溯 E2E。

验证：
1. 未认证 → /start 出引导（不是主菜单）
2. 认证后 → /start 出主菜单（含 7 项按钮）
3. ① 同步认证 → 显示身份/钱包/额度/子身份
4. ② 收款明细 → 无订单提示
5. ③ 付款订单 → 无订单提示
6. ④ 进行中订单 → 无订单提示
7. ⑤ 争议订单 → 无订单提示
8. ⑥ 我的积分 → 显示积分/信誉
9. ⑦ 邀请码&下级 → 显示邀请码/分享链接
10. 子身份绑定 TG → Bot 回溯主身份 → 菜单显示主身份数据
11. 下单后 → 收款/付款/进行中菜单正确显示
12. 订单详情 → 完整信息
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

TG_MAIN = 960000000 + int(time.time()) % 100000
TG_SUB = TG_MAIN + 1
TG_SELLER = TG_MAIN + 2


def make_init_data(tg_id, username):
    params = {
        "auth_date": str(int(time.time())),
        "query_id": f"menu-{tg_id}",
        "user": json.dumps({"id": tg_id, "first_name": "Menu", "username": username}),
    }
    cs = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, cs.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def webhook(update):
    r = httpx.post(BASE + "/v1/telegram/bot/webhook", json=update,
                   headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def msg(tg_id, text):
    return webhook({
        "update_id": int(time.time()),
        "message": {
            "message_id": int(time.time()) % 100000, "date": int(time.time()), "text": text,
            "from": {"id": tg_id, "is_bot": False, "first_name": "Menu"},
            "chat": {"id": tg_id, "type": "private"},
        },
    })


def cbq(tg_id, data):
    return webhook({
        "update_id": int(time.time()),
        "callback_query": {
            "id": f"cbq_{tg_id}_{int(time.time()*1000)%99999}",
            "from": {"id": tg_id, "is_bot": False, "first_name": "Menu"},
            "data": data,
            "message": {"message_id": 1, "chat": {"id": tg_id, "type": "private"}, "date": int(time.time())},
        },
    })


def login_with_tg(tg_id, username, acct):
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


def _kb_texts(result):
    """提取 reply_markup 所有按钮文本（兼容 inline keyboard 与 reply keyboard）。"""
    rm = result.get("reply_markup", {})
    kb = rm.get("inline_keyboard") or rm.get("keyboard") or []
    return [b["text"] for row in kb for b in row]


def _kb_data(result):
    """提取 reply_markup 所有按钮 callback_data。"""
    kb = result.get("reply_markup", {}).get("inline_keyboard", [])
    return [b["callback_data"] for row in kb for b in row]


# ── 测试开始 ──

main_acct = Account.create()
seller_acct = Account.create()

with httpx.Client(base_url=BASE, timeout=30) as c:
    # 1. 未认证用户 /start → 引导 2FA 绑定（不再跳操作台）
    result = msg(TG_MAIN, "/start")
    assert result["action"] == "bind_prompt", result
    assert "主身份ID" in result["reply_text"], result["reply_text"]
    assert "2FA" in result["reply_text"], result["reply_text"]
    print("1. 未认证→引导2FA绑定         OK")

    # 2. 主身份认证后 /start → 主菜单（Reply Keyboard 菜单栏）
    main_sid, main_kid = login_with_tg(TG_MAIN, "menu_main", main_acct)
    result = msg(TG_MAIN, "/start")
    assert result["action"] == "menu_main", result
    assert "已认证" in result["reply_text"], result["reply_text"]
    texts = _kb_texts(result)
    assert "🔗 同步认证" in texts, texts
    assert "📥 收款明细" in texts, texts
    assert "📤 付款订单" in texts, texts
    assert "⏳ 进行中订单" in texts, texts
    assert "⚖️ 争议订单" in texts, texts
    assert "🌟 我的积分" in texts, texts
    assert "👥 邀请码&下级" in texts, texts
    print("2. 认证后→主菜单(7项)        OK")

    # 3. ① 同步认证
    result = cbq(TG_MAIN, "karma_menu:sync")
    assert result["action"] == "menu_sync", result
    assert "认证账户同步" in result["reply_text"], result["reply_text"]
    assert main_kid in result["reply_text"], "应显示身份ID"
    assert "子身份：未创建" in result["reply_text"], result["reply_text"]
    print("3. ①同步认证                OK")

    # 4. ② 收款明细（无订单）
    result = cbq(TG_MAIN, "karma_menu:receipts")
    assert result["action"] == "menu_receipts", result
    assert "暂无收款记录" in result["reply_text"], result["reply_text"]
    print("4. ②收款明细(空)            OK")

    # 5. ③ 付款订单（无订单）
    result = cbq(TG_MAIN, "karma_menu:payments")
    assert result["action"] == "menu_payments", result
    assert "暂无付款记录" in result["reply_text"], result["reply_text"]
    print("5. ③付款订单(空)            OK")

    # 6. ④ 进行中订单（无订单）
    result = cbq(TG_MAIN, "karma_menu:ongoing")
    assert result["action"] == "menu_ongoing", result
    assert "暂无进行中" in result["reply_text"], result["reply_text"]
    print("6. ④进行中订单(空)          OK")

    # 7. ⑤ 争议订单（无订单）
    result = cbq(TG_MAIN, "karma_menu:disputes")
    assert result["action"] == "menu_disputes", result
    assert "暂无争议" in result["reply_text"], result["reply_text"]
    print("7. ⑤争议订单(空)            OK")

    # 8. ⑥ 我的积分
    result = cbq(TG_MAIN, "karma_menu:points")
    assert result["action"] == "menu_points", result
    assert "Karma 积分" in result["reply_text"], result["reply_text"]
    assert "信誉评分" in result["reply_text"], result["reply_text"]
    print("8. ⑥我的积分                OK")

    # 9. ⑦ 邀请码&下级
    result = cbq(TG_MAIN, "karma_menu:invite")
    assert result["action"] == "menu_invite", result
    assert "邀请码" in result["reply_text"], result["reply_text"]
    assert "hookkarma_bot?start=ref_" in result["reply_text"], result["reply_text"]
    invite_code = None
    for line in result["reply_text"].splitlines():
        if "我的邀请码：" in line:
            invite_code = line.split("：")[1].strip()
    assert invite_code and len(invite_code) == 8, invite_code
    print(f"9. ⑦邀请码&下级             OK (code={invite_code})")

    # 10. 子身份体系：主身份创建子身份 → 子身份绑定 TG → Bot 回溯主身份
    sub_acct = Account.create()
    r = c.post("/v1/identities/sub", headers={"Authorization": f"Bearer {main_sid}"},
               json={"parent_identity_id": main_kid, "wallet": sub_acct.address})
    assert r.status_code == 200, r.text
    sub_kid = r.json()["identity_id"]
    assert r.json().get("parent_identity_id") == main_kid, r.text
    print(f"10. 主身份创建子身份         OK -> {sub_kid[:14]}")

    # 子身份绑定 TG
    _, _ = login_with_tg(TG_SUB, "menu_sub", sub_acct)
    # 通过 /v1/telegram/bind 绑定子身份到 TG_SUB
    r = c.post("/v1/telegram/session", json={"init_data": make_init_data(TG_SUB, "menu_sub")})
    sub_sid = r.json()["session_id"]
    sub_auth = {"Authorization": f"Bearer {sub_sid}"}
    c.post("/v1/telegram/bind", headers=sub_auth, json={"init_data": make_init_data(TG_SUB, "menu_sub"), "identity_id": sub_kid})

    # 子身份 TG /start → 回溯到主身份（显示主身份的额度）
    result = msg(TG_SUB, "/start")
    assert result["action"] == "menu_main", result
    assert "已认证" in result["reply_text"], result["reply_text"]
    # 主身份的额度 2000U 应该出现在子身份的菜单里
    assert "2000" in result["reply_text"], f"子身份应回溯主身份额度: {result['reply_text']}"
    print("10. 子身份回溯主身份额度     OK")

    # 子身份点同步 → 显示子身份数量
    result = cbq(TG_SUB, "karma_menu:sync")
    assert result["action"] == "menu_sync", result
    assert "子身份：1 个" in result["reply_text"], result["reply_text"]
    assert main_kid in result["reply_text"], "应显示主身份ID"
    print("10. 子身份同步显示主身份     OK")

    # 11. 商家上架 → 买家下单 → 菜单列表正确显示
    seller_sid, seller_kid = login_with_tg(TG_SELLER, "menu_seller", seller_acct)
    r = c.post("/v1/registry/agents", headers={"Authorization": f"Bearer {seller_sid}"},
               json={"endpoint": "https://agent.example.com/hook", "capabilities": [], "wallet": seller_acct.address})
    agent = r.json()
    r = c.post("/v1/registry/capabilities", headers={"Authorization": f"Bearer {seller_sid}"},
               json={"name": "Menu Test", "category": "digital", "description": "menu e2e"})
    cap = r.json()
    r = c.post("/v1/registry/offers", headers={"Authorization": f"Bearer {seller_sid}"},
               json={"agent_id": agent["agent_id"], "capability_id": cap["capability_id"],
                     "title": "menu 测试服务", "price_usdc": "15", "category": "digital",
                     "seller_wallet": seller_acct.address})
    offer_id = r.json()["offer_id"]

    # 主身份买家下单
    result = msg(TG_MAIN, "帮我找数据抓取服务，预算 20 USDC")
    assert result["action"] == "recommend", result
    result = cbq(TG_MAIN, f"karma_pick:{offer_id}")
    assert result["action"] == "bill_confirm", result
    result = cbq(TG_MAIN, f"karma_confirm:{offer_id}")
    assert result["action"] == "order_created", result
    order_id = result["order_id"]
    print(f"11. 下单→锁仓               OK -> {order_id[:14]}")

    # 商家接单
    result = cbq(TG_SELLER, f"karma_accept:{order_id}")
    assert result["action"] == "accepted", result
    print("11. 商家接单                OK")

    # 买家付款订单菜单 → 应有 1 单
    result = cbq(TG_MAIN, "karma_menu:payments")
    assert "menu 测试服务" in result["reply_text"], result["reply_text"]
    assert order_id[:14] in result["reply_text"], result["reply_text"]
    print("11. ③付款订单有记录         OK")

    # 进行中订单菜单 → 应有 1 单
    result = cbq(TG_MAIN, "karma_menu:ongoing")
    assert order_id[:14] in result["reply_text"], result["reply_text"]
    print("11. ④进行中订单有记录       OK")

    # 商家收款明细菜单 → 应有 1 单
    result = cbq(TG_SELLER, "karma_menu:receipts")
    assert "menu 测试服务" in result["reply_text"], result["reply_text"]
    assert order_id[:14] in result["reply_text"], result["reply_text"]
    print("11. ②收款明细有记录         OK")

    # 12. 订单详情
    result = cbq(TG_MAIN, f"karma_detail:{order_id}")
    assert result["action"] == "menu_detail", result
    assert order_id in result["reply_text"], result["reply_text"]
    assert "15" in result["reply_text"], result["reply_text"]
    assert "买家" in result["reply_text"], result["reply_text"]
    print("12. 订单详情                OK")

print("\n=== ALL 12/12 PASS ===")
