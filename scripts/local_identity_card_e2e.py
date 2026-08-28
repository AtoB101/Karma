"""身份底座 v1 —— Identity Card / 凭证链 / 状态机播报 E2E（走运行中服务 HTTP 全链路）。

验证：
1. 种子身份 → 签发 3 类凭证 → Card 达到 enhanced
2. Card 最小披露：不含 2FA 明文 / 完整钱包
3. 非法迁移（revoked→verify）→ HTTP 409 + 告警流出现 illegal_transition + 根因链
4. 吊销凭证 → Card 验证等级降级
5. 2FA 绑定（webhook）→ telegram 凭证自动 verified + 明文焚毁
6. 信任台账 hash 链完整 + 环境健康
7. 输入校验：坏 identity_id / scope → 400
"""
import time

import httpx

BASE = "http://127.0.0.1:8000"
_env = open(".env").read()
WEBHOOK_SECRET = _env.split("TELEGRAM_WEBHOOK_SECRET=")[1].splitlines()[0].strip()

TS = int(time.time())
KID = f"kid_card_e2e_{TS}"
WALLET = "0x" + "cd" * 20
TWOfa = "731959"
TG_USER = 960000000 + TS % 100000

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
            "from": {"id": tg_id, "is_bot": False, "first_name": "Card", "username": f"card{tg_id%1000}"},
            "chat": {"id": tg_id, "type": "private"},
        },
    })


def main():
    # ── 0. 种子身份 ──
    r = _client.post("/v1/telegram/test/seed", json={"identity_id": KID, "twofa_code": TWOfa})
    assert r.status_code == 200, r.text
    print("0. 种子身份                  OK")

    # ── 1. 签发 3 类凭证 → enhanced（issue+verify 两步，模拟独立验证材料） ──
    for t in ("email", "phone", "wallet"):
        r = _client.post(f"/v1/identity/{KID}/credentials", json={"type": t})
        assert r.status_code == 200, r.text
        cid = r.json()["credential"]["credential_id"]
        assert r.json()["credential"]["status"] == "pending", r.text
        r = _client.post(f"/v1/identity/{KID}/credentials/{cid}/verify")
        assert r.status_code == 200, r.text
        assert r.json()["credential"]["status"] == "verified", r.text
    r = _client.get(f"/v1/identity/{KID}/card", params={"scope": "full"})
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["verification_status"] == "enhanced", card
    assert card["verification_level"]["enhanced"] is True, card
    print("1. 3凭证→Card enhanced       OK")

    # ── 2. 最小披露 ──
    card_str = str(card)
    assert TWOfa not in card_str, "2FA 明文泄露！"
    assert WALLET not in card_str, "完整钱包地址泄露！"
    assert "…" in card["wallet"], card["wallet"]
    print("2. Card 最小披露             OK")

    # ── 3. 非法迁移 → 409 + 播报 ──
    r = _client.get(f"/v1/identity/{KID}/card", params={"scope": "full"})
    creds = r.json()["credentials"]
    phone_cred = [c for c in creds if c["type"] == "phone"][0]
    r = _client.post(f"/v1/identity/{KID}/credentials/{phone_cred['credential_id']}/revoke",
                     json={"reason": "e2e revoke test"})
    assert r.status_code == 200, r.text
    r = _client.post(f"/v1/identity/{KID}/credentials/{phone_cred['credential_id']}/verify")
    assert r.status_code == 409, f"非法迁移应 409: {r.status_code} {r.text}"
    r = _client.get("/v1/trust/alerts", params={"severity": "warn"})
    alerts = r.json()["alerts"]
    illegal = [a for a in alerts if a["category"] == "illegal_transition"]
    assert illegal, "告警流缺 illegal_transition"
    assert isinstance(illegal[0]["root_cause"], list), "告警缺根因回溯链"
    print("3. 非法迁移409+播报+根因     OK")

    # ── 4. 吊销后 Card 降级 ──
    r = _client.get(f"/v1/identity/{KID}/card")
    card = r.json()
    assert card["verification_status"] == "basic", card  # email+wallet 剩 2 类
    print("4. 吊销→Card 降级 basic      OK")

    # ── 5. 2FA 绑定 → telegram 凭证自动 verified + 明文焚毁 ──
    r = msg(TG_USER, "/start")
    r = msg(TG_USER, f"{KID} {TWOfa}")
    assert r["action"] == "bind_success", r
    r = _client.get(f"/v1/identity/{KID}/card", params={"scope": "full"})
    tg_creds = [c for c in r.json()["credentials"] if c["type"] == "telegram"]
    assert len(tg_creds) == 1 and tg_creds[0]["status"] == "verified", r.text
    r = msg(TG_USER, "重新绑定")
    assert r["action"] == "bind_prompt", r
    r = msg(TG_USER, f"{KID} {TWOfa}")
    assert r["action"] == "bind_failed", "焚毁后同码重试应拒绝"
    r = msg(TG_USER, "取消")
    print("5. 2FA绑定→凭证verified+焚毁 OK")

    # ── 6. 台账完整 + 健康自检 ──
    r = _client.post("/v1/trust/verify-integrity")
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    r = _client.get("/v1/trust/health")
    assert r.json()["ok"] is True, r.text
    r = _client.get("/v1/trust/ledger", params={"entity_id": KID, "limit": 10})
    entries = r.json()["entries"]
    assert any(e["event"] == "card_presented" for e in entries), "缺 card_presented 审计"
    print("6. 台账hash链完整+健康OK     OK")

    # ── 7. 输入校验 ──
    r = _client.get("/v1/identity/../../etc/passwd/card")
    assert r.status_code in (400, 404), r.status_code
    r = _client.get(f"/v1/identity/{KID}/card", params={"scope": "secret"})
    assert r.status_code == 422, r.status_code
    r = _client.post(f"/v1/identity/{KID}/credentials", json={"type": "passport"})
    assert r.status_code == 400, r.text
    print("7. 输入校验（路径/枚举/白名单）OK")

    print("\n=== ALL 8/8 PASS ===")


if __name__ == "__main__":
    main()
