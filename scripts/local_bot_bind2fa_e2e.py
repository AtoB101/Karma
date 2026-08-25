"""Bot 2FA 快速绑定 + Reply Keyboard 菜单 E2E。

验证：
1. 未认证 /start → 绑定引导（含菜单键盘）
2. 输入「主身份ID 2FA码」→ 绑定成功（含钱包/额度摘要）
3. 菜单按钮文本路由（🔗 同步认证 等）正常工作
4. 错误 2FA → 拒绝
5. 绑定后发需求 → 推荐 → 账单卡 → 确认 → LOCKED
6. 「重新绑定」→ 换绑商家身份 → 商家收款明细有订单
7. 商家一键接单 → ACCEPTED
"""
import time

import httpx

BASE = "http://127.0.0.1:8000"
_env = open(".env").read()
WEBHOOK_SECRET = _env.split("TELEGRAM_WEBHOOK_SECRET=")[1].splitlines()[0].strip()

TG_USER = 950000000 + int(time.time()) % 100000

BUYER_ID = "kid_e2e_buyer01"
BUYER_2FA = "246810"
# 每次运行用唯一商家身份：新 offer 按上架时间优先排在推荐首位，测试确定性
SELLER_ID = f"kid_e2e_seller_{int(time.time())}"
SELLER_2FA = "135790"


_client = httpx.Client(base_url=BASE, timeout=30)


def webhook(update):
    r = _client.post("/v1/telegram/bot/webhook", json=update,
                     headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET})
    assert r.status_code == 200, r.text
    return r.json()


def msg(tg_id, text):
    return webhook({
        "update_id": int(time.time()),
        "message": {
            "message_id": int(time.time()) % 100000, "date": int(time.time()), "text": text,
            "from": {"id": tg_id, "is_bot": False, "first_name": "Bind", "username": f"bind{tg_id%1000}"},
            "chat": {"id": tg_id, "type": "private"},
        },
    })


def cbq(tg_id, data):
    return webhook({
        "update_id": int(time.time()),
        "callback_query": {
            "id": f"cbq_{tg_id}_{int(time.time()*1000)%99999}",
            "from": {"id": tg_id, "is_bot": False, "first_name": "Bind"},
            "data": data,
            "message": {"message_id": 1, "chat": {"id": tg_id, "type": "private"}, "date": int(time.time())},
        },
    })


def main():
    # ── 0. 通过服务端种子接口创建测试身份（服务进程内状态+落盘同步） ──
    r = _client.post("/v1/telegram/test/seed",
                     json={"identity_id": BUYER_ID, "twofa_code": BUYER_2FA})
    assert r.status_code == 200, r.text
    r = _client.post("/v1/telegram/test/seed",
                     json={"identity_id": SELLER_ID, "twofa_code": SELLER_2FA,
                           "as_seller": True, "offer_title": "E2E 数据抓取服务", "offer_price_usdc": "15"})
    assert r.status_code == 200, r.text
    seller_offer_id = r.json()["offer_id"]
    assert seller_offer_id, "种子接口应返回新 offer_id（商家身份每次唯一，必新建）"
    print("0. 种子身份/商品              OK")

    # 1. 未认证 /start → 绑定引导
    r = msg(TG_USER, "/start")
    assert "2FA" in r["reply_text"] or "2fa" in r["reply_text"].lower(), r["reply_text"]
    assert r.get("reply_markup", {}).get("keyboard"), "应有 Reply Keyboard 菜单"
    print("1. /start→绑定引导+菜单键盘   OK")

    # 2. 错误 2FA → 拒绝
    r = msg(TG_USER, f"{BUYER_ID} 000000")
    assert r["action"] == "bind_failed", r
    print("2. 错误2FA→拒绝              OK")

    # 3. 正确绑定（成功后 2FA 明文焚毁）
    r = msg(TG_USER, f"{BUYER_ID} {BUYER_2FA}")
    assert r["action"] == "bind_success", r
    assert r["identity_id"] == BUYER_ID and "认证成功" in r["reply_text"], r
    assert "焚毁" in r["reply_text"], r["reply_text"]
    print("3. ID+2FA→认证成功(明文焚毁)  OK")

    # 3b. 焚毁后同码重试 → 拒绝
    r = msg(TG_USER, "重新绑定")
    assert r["action"] == "bind_prompt", r
    r = msg(TG_USER, f"{BUYER_ID} {BUYER_2FA}")
    assert r["action"] == "bind_failed", r
    print("3b. 焚毁后重试→拒绝          OK")
    r = msg(TG_USER, "取消")
    assert r["action"] == "bind_cancelled", r

    # 4. 菜单按钮文本路由
    r = msg(TG_USER, "🔗 同步认证")
    assert r["action"] == "menu_sync" and BUYER_ID in r["reply_text"], r["reply_text"][:100]
    r = msg(TG_USER, "🌟 我的积分")
    assert r["action"] == "menu_points", r
    print("4. 菜单按钮文本路由          OK")

    # 5. 发需求 → 推荐 → 账单卡 → 确认 → LOCKED
    r = msg(TG_USER, "帮我找数据抓取服务，预算 20 USDC")
    assert "已认证" in r["reply_text"], r["reply_text"][:200]
    buttons = r.get("reply_markup", {}).get("inline_keyboard") or []
    assert buttons, r["reply_text"][:200]
    # 精确选种子商家的 offer（环境中可能存在信誉更高的累积商家排第一）
    all_data = [b["callback_data"] for row in buttons for b in row]
    assert f"karma_pick:{seller_offer_id}" in all_data, (
        f"种子商家 offer 未进 TOP{len(buttons)} 推荐：{all_data}（请检查推荐排序）")
    offer_id = seller_offer_id
    r = cbq(TG_USER, f"karma_pick:{offer_id}")
    assert "账单" in r["reply_text"], r["reply_text"][:200]
    r = cbq(TG_USER, f"karma_confirm:{offer_id}")
    assert r["action"] == "order_created", r
    order_id = r["order_id"]
    print("5. 需求→账单→确认→锁仓      OK ->", order_id[:14])

    # 6. 重新绑定 → 换绑商家
    r = msg(TG_USER, "重新绑定")
    assert r["action"] == "bind_prompt", r
    r = msg(TG_USER, f"{SELLER_ID} {SELLER_2FA}")
    assert r["action"] == "bind_success" and r["identity_id"] == SELLER_ID, r
    print("6. 重新绑定→换绑商家         OK")

    # 7. 商家收款明细有订单 + 一键接单
    r = msg(TG_USER, "📥 收款明细")
    assert order_id[:14] in r["reply_text"], r["reply_text"][:300]
    print("7. 商家收款明细有订单        OK")
    r = cbq(TG_USER, f"karma_accept:{order_id}")
    assert r["action"] == "accepted", r
    print("8. 商家一键接单              OK -> ACCEPTED")

    print("\n=== ALL 8/8 PASS ===")


if __name__ == "__main__":
    main()
