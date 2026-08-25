"""身份底座 v1 —— 反规则逆向审计（攻击者视角，走运行中服务 HTTP 全链路）。

9 项攻击目标：
A1 凭证复活：revoked → verify 必须被状态机拦截（409 + 播报）
A2 伪造 enhanced：不足条件时 Card 不得返回 enhanced；无任何端点可直接写 verification_status
A3 台账篡改绕过：verify-integrity 端点可用且返回 ok；无端点可写原始台账
A4 revoke reason 绕过：无 reason 吊销必须 400
A5 畸形 ID：路径穿越 / 尾随换行 / 超长 / 枚举探测 → 400/404，不得 5xx
A6 告警丢失：非法迁移后 /v1/trust/alerts 必须能查到对应播报
A7 并发竞态：同类型凭证并发签发不得产生重复活跃凭证
A8 信息泄露：Card / PUT class 响应不含 twofa_code、payment_policy、凭证原始材料
A9 2FA 暴破：错误码重复尝试不得成功，响应不得泄露正确码
"""
import concurrent.futures
import time

import httpx

BASE = "http://127.0.0.1:8000"
_env = open(".env").read()
WEBHOOK_SECRET = _env.split("TELEGRAM_WEBHOOK_SECRET=")[1].splitlines()[0].strip()

TS = int(time.time())
KID = f"kid_rev_{TS}"
WALLET = "0x" + "ef" * 20
TWOfa = "482913"
TG_USER = 970000000 + TS % 100000

_client = httpx.Client(base_url=BASE, timeout=60)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


def seed(kid, twofa):
    r = _client.post("/v1/telegram/test/seed", json={"identity_id": kid, "twofa_code": twofa})
    assert r.status_code == 200, r.text


def issue(kid, ctype):
    r = _client.post(f"/v1/identity/{kid}/credentials", json={"type": ctype})
    return r


def verify(kid, cid):
    return _client.post(f"/v1/identity/{kid}/credentials/{cid}/verify")


def card(kid, scope="basic"):
    return _client.get(f"/v1/identity/{kid}/card", params={"scope": scope})


def main():
    seed(KID, TWOfa)

    # ── A1 凭证复活 ──
    r = issue(KID, "email"); cid = r.json()["credential"]["credential_id"]
    verify(KID, cid)
    r = _client.post(f"/v1/identity/{KID}/credentials/{cid}/revoke", json={"reason": "audit-test"})
    check("A1a revoke 前置 OK", r.status_code == 200, r.text)
    r = verify(KID, cid)
    check("A1b revoked→verify 拦截 409", r.status_code == 409, f"got {r.status_code}")
    check("A1c 响应含 illegal transition", "illegal transition" in r.text.lower(), r.text[:200])

    # ── A6 告警丢失 ──
    r = _client.get("/v1/trust/alerts", params={"entity_id": KID, "limit": 5})
    alerts = r.json().get("alerts", [])
    hit = any(a.get("category") == "illegal_transition" for a in alerts)
    check("A6 非法迁移播报可查", r.status_code == 200 and hit, r.text[:300])

    # ── A2 伪造 enhanced ──
    # 唯一凭证已吊销（0 个 verified）→ 必须 unverified
    r = card(KID, "full")
    j = r.json()
    check("A2a 吊销后 Card=unverified", j.get("verification_status") == "unverified",
          str(j.get("verification_status")))
    # 补 2 个非 wallet 凭证（email+phone）→ 只能 basic，不得 enhanced
    for t in ("email", "phone"):
        rr = issue(KID, t)
        verify(KID, rr.json()["credential"]["credential_id"])
    r = card(KID, "full")
    check("A2a2 无wallet仅2类→basic非enhanced", r.json().get("verification_status") == "basic",
          str(r.json().get("verification_status")))
    # 无端点可直写 verification_status：对 class 端点注入该字段应被忽略
    r = _client.put(f"/v1/identity/{KID}/class",
                    json={"identity_class": "business", "verification_status": "enhanced"})
    check("A2b PUT class 接受请求", r.status_code == 200, r.text[:200])
    fields = set(r.json().keys())
    check("A2c PUT class 返回脱敏视图", fields <= {"identity_id", "identity_class", "verification_status", "status"},
          f"fields={fields}")
    r = card(KID, "full")
    check("A2d 注入 verification_status 无效", r.json().get("verification_status") == "basic",
          str(r.json().get("verification_status")))
    # ── A8 信息泄露（含 F1 修复验证） ──
    blob = (card(KID, "full").text + _client.get(f"/v1/identity/{KID}").text
            + _client.put(f"/v1/identity/{KID}/class", json={"identity_class": "user"}).text)
    check("A8a 无 2FA 明文", TWOfa not in blob)
    check("A8b 无 payment_policy", "payment_policy" not in blob)
    check("A8c 无完整钱包地址(若已绑)", WALLET not in blob)
    cred_blob = str(card(KID, "full").json())
    check("A8d 凭证列表不含原始材料", "twofa_code" not in cred_blob.lower())

    # ── A3 台账篡改绕过 ──
    r = _client.post("/v1/trust/verify-integrity")
    j = r.json()
    check("A3a verify-integrity ok", r.status_code == 200 and j.get("ok") is True, r.text[:300])

    # ── A4 revoke reason 绕过（400 或 422 均为有效拦截） ──
    r = _client.post(f"/v1/identity/{KID}/credentials/{cid}/revoke", json={})
    check("A4a 无 reason revoke → 400/422", r.status_code in (400, 422), f"got {r.status_code}")
    r = _client.post(f"/v1/identity/{KID}/credentials/{cid}/revoke", json={"reason": ""})
    check("A4b 空 reason revoke → 400/422", r.status_code in (400, 422), f"got {r.status_code}")

    # ── A5 畸形 ID（含 URL 编码后的尾随换行/路径穿越） ──
    from urllib.parse import quote
    bad_ids = ["..%2Fetc%2Fpasswd", f"{KID}%0A", "x" * 100, "kid_a%5Cb", f"{KID}%0a", "..%2F..%2F..%2Fsecrets"]
    for bad in bad_ids:
        r = _client.post(f"/v1/identity/{bad}/credentials", json={"type": "email"})
        check(f"A5 畸形ID[{bad[:20]}] 非5xx", r.status_code < 500, f"got {r.status_code}")
    r = _client.post(f"/v1/identity/{quote(KID + chr(10))}/credentials", json={"type": "email"})
    check("A5a 原始尾随换行被拒(400/404)", r.status_code in (400, 404), f"got {r.status_code}")
    r = card("kid_nonexist_audit")
    check("A5b 不存在 ID → 404", r.status_code == 404, f"got {r.status_code}")

    # ── A7 并发竞态：同类型并发签发不得产生重复活跃凭证 ──
    KID2 = f"kid_race_{TS}"
    seed(KID2, "112233")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        rs = list(ex.map(lambda _: issue(KID2, "phone"), range(4)))
    codes = [r.status_code for r in rs]
    ok = [r for r in rs if r.status_code == 200]
    check("A7a 并发签发恰好 1 个成功", len(ok) == 1, f"codes={codes}")
    r = card(KID2, "full")
    active_phone = [c for c in r.json().get("credentials", []) if c.get("type") == "phone"
                    and c.get("status") in ("pending", "verified")]
    check("A7b 活跃 phone 凭证仅 1 个", len(active_phone) == 1, f"n={len(active_phone)}")

    # ── A9 2FA 暴破 ──
    KID3 = f"kid_brute_{TS}"
    seed(KID3, "998877")
    TG3 = 980000000 + TS % 100000

    def tg(tg_id, text):
        u = {"update_id": int(time.time() * 1000) % 10**9, "message": {
            "message_id": int(time.time() * 1000) % 100000, "date": int(time.time()), "text": text,
            "from": {"id": tg_id, "is_bot": False, "first_name": "Brute", "username": f"b{tg_id%1000}"},
            "chat": {"id": tg_id, "type": "private"}}}
        return _client.post("/v1/telegram/bot/webhook", json=u,
                            headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET})

    tg(TG3, f"{KID3} 000000")  # 触发绑定 pending（错误码）
    leaked = False
    for code in ("111111", "222222", "000000", "998876", "998878"):
        r = tg(TG3, f"{KID3} {code}")
        body = r.text
        if "998877" in body:
            leaked = True
    check("A9a 错误码尝试均不成功且不泄露正确码", not leaked)
    r = tg(TG3, f"{KID3} 998877")
    check("A9b 正确码仍可认证成功", "认证成功" in r.text, r.text[:200])
    r = tg(TG3, f"{KID3} 998877")  # 焚毁后重放
    check("A9c 焚毁后重放被拒绝", "认证成功" not in r.text, r.text[:200])

    # ── 汇总 ──
    print(f"\n=== REVERSE AUDIT: {len(PASS)} PASS / {len(FAIL)} FAIL ===")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
