# -*- coding: utf-8 -*-
"""安全回执（操作台「站内提醒」）的覆盖面：不能只覆盖钥匙，资金权限与第二把锁也要留痕。

用户口径（2026-10-08）：凡是安全相关的变化，都要让主人**事后在操作台看得见**。
以前站内提醒只有两条来源 —— 接入生效（key_bound）和取消绑定（key_unbound）。
于是两类同样要命的变化是静默的：

* **授权额度**（子身份额度的加 / 减 / 清零）：取消授权 = 把支配权收回来，页面上闪一下
  就没了，主人下次进来什么也看不到；
* **第二把锁（2FA）本身被改动**（绑上 / 解绑 / 换恢复码）：锁被拆了没有回执。

这个文件钉两件事：
  1. 后端：这三类动作各自落一条 ConsoleNoticeModel（走真实路由 + 真实库）；
  2. 前端：这几条回执在操作台画得出文案，且五份词表都有译文（不留中文）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import CapacityModel, ConsoleNoticeModel, IdentityRoleProfile
from services import console_2fa

ROOT = Path(__file__).resolve().parents[2]
CONSOLE_NOTICE = ROOT / "services" / "console_notice.py"
CONSOLE_2FA_ROUTE = ROOT / "api" / "routes" / "console_2fa.py"
CAPACITY_ROUTE = ROOT / "api" / "routes" / "capacity.py"
NOTICE_JS = ROOT / "apps" / "console" / "scripts" / "cyber-unbind-keys.js"
PHRASES = ROOT / "apps" / "console" / "scripts" / "i18n-phrase"

KIND_2FA_ENABLED = "2fa_enabled"
KIND_2FA_DISABLED = "2fa_disabled"
KIND_2FA_RECOVERY = "2fa_recovery_rotated"
KIND_ALLOCATIONS = "allocations_changed"

RECEIPT_SENTENCES = (
    "授权额度已变更：当前已授权合计 {0} USDC。",
    "第二把锁（安全验证）已绑定：以后动资金要多输一次验证码。",
    "第二把锁（安全验证）已解绑：动资金现在只靠钱包签名。",
    "第二把锁的恢复码已换新：旧的那一组作废了。",
)


def _hdr(identity: str) -> dict[str, str]:
    return {"X-Karma-Identity-Id": identity}


async def _kinds(client: AsyncClient, identity: str) -> list[str]:
    resp = await client.post(
        "/runtime/list-notices",
        json={"karma_identity_id": identity},
        headers=_hdr(identity),
    )
    assert resp.status_code == 200, resp.text
    return [n["kind"] for n in resp.json()["notices"]]


# ---------------------------------------------------------------------------
# 1. 后端：三类动作各自要留一条回执
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_2fa_enable_disable_and_recovery_all_leave_receipts(
    client: AsyncClient, db_session: AsyncSession
):
    identity = "kid-receipt-2fa"

    enroll = await client.post("/v1/console/2fa/enroll", headers=_hdr(identity))
    assert enroll.status_code == 201, enroll.text
    secret = enroll.json()["secret"]

    activated = await client.post(
        "/v1/console/2fa/activate", json={"code": console_2fa.totp(secret)}, headers=_hdr(identity)
    )
    assert activated.status_code == 200, activated.text
    assert KIND_2FA_ENABLED in await _kinds(client, identity), "绑上第二把锁必须留回执"

    rotated = await client.post(
        "/v1/console/2fa/recovery", json={"code": console_2fa.totp(secret)}, headers=_hdr(identity)
    )
    assert rotated.status_code == 200, rotated.text
    assert KIND_2FA_RECOVERY in await _kinds(client, identity), "换恢复码必须留回执"

    disabled = await client.post(
        "/v1/console/2fa/disable", json={"code": console_2fa.totp(secret)}, headers=_hdr(identity)
    )
    assert disabled.status_code == 200, disabled.text
    assert KIND_2FA_DISABLED in await _kinds(client, identity), "解绑第二把锁必须留回执"

    # 回执是本人私有的：别人读不到。
    other = await client.post(
        "/runtime/list-notices",
        json={"karma_identity_id": identity},
        headers=_hdr("kid-receipt-other"),
    )
    assert other.status_code == 403, other.text


@pytest.mark.asyncio
async def test_setting_allocations_leaves_a_receipt(
    client: AsyncClient, db_session: AsyncSession
):
    identity = "kid-receipt-alloc"
    profile_id = "prof-receipt-alloc"
    db_session.add(
        CapacityModel(identity_id=identity, total_locked_usdc=100.0, available_credits=100.0)
    )
    db_session.add(
        IdentityRoleProfile(
            profile_id=profile_id, owner_identity_id=identity, class_="life", status="active"
        )
    )
    await db_session.commit()

    resp = await client.put(
        f"/v1/capacity/{identity}/allocations",
        json={"allocations": {profile_id: 40.0}},
        headers=_hdr(identity),
    )
    assert resp.status_code == 200, resp.text

    rows = (
        await db_session.execute(
            ConsoleNoticeModel.__table__.select().where(
                ConsoleNoticeModel.karma_identity_id == identity
            )
        )
    ).all()
    kinds = [r.kind for r in rows]
    assert KIND_ALLOCATIONS in kinds, "改授权额度必须留回执"
    payload = [r.payload for r in rows if r.kind == KIND_ALLOCATIONS][0]
    assert payload["total_allocated"] == pytest.approx(40.0)
    assert payload["allocations"][0]["profile_id"] == profile_id


# ---------------------------------------------------------------------------
# 2. 静态接线：写回执的地方不许再漏
# ---------------------------------------------------------------------------

def test_all_kinds_are_declared_once():
    src = CONSOLE_NOTICE.read_text(encoding="utf-8")
    for kind in (KIND_2FA_ENABLED, KIND_2FA_DISABLED, KIND_2FA_RECOVERY, KIND_ALLOCATIONS):
        assert re.search(r'^\w+ = "%s"$' % kind, src, re.M), "console_notice 里少了 %s" % kind
    assert "async def add_notice_safe(" in src, "回执写入要收敛到一个「失败不影响主流程」的入口"


def test_routes_write_the_receipts():
    twofa = CONSOLE_2FA_ROUTE.read_text(encoding="utf-8")
    for const in ("NOTICE_2FA_ENABLED", "NOTICE_2FA_DISABLED", "NOTICE_2FA_RECOVERY_ROTATED"):
        assert const in twofa, "console_2fa 路由没写 %s 回执" % const
    assert twofa.count("add_notice_safe(") == 3, "绑上 / 换恢复码 / 解绑三条路各要留一条"
    cap = CAPACITY_ROUTE.read_text(encoding="utf-8")
    assert "NOTICE_ALLOCATIONS_CHANGED" in cap and "add_notice_safe(" in cap


def test_console_renders_the_new_receipts():
    js = NOTICE_JS.read_text(encoding="utf-8")
    for kind in (KIND_2FA_ENABLED, KIND_2FA_DISABLED, KIND_2FA_RECOVERY, KIND_ALLOCATIONS):
        assert '"%s"' % kind in js, "操作台没处理 %s 这条回执" % kind
    for sentence in RECEIPT_SENTENCES:
        assert sentence in js, "回执文案没接线：%s" % sentence


@pytest.mark.parametrize("lang", ("en", "ja", "ko", "es-AR", "es-SV"))
def test_every_receipt_sentence_is_translated(lang):
    entries = {}
    for line in (PHRASES / (lang + ".js")).read_text(encoding="utf-8").split("\n"):
        m = re.match(r'^\s*"((?:[^"\\]|\\.)*)":\s*"((?:[^"\\]|\\.)*)",?\s*$', line)
        if m:
            entries[m.group(1)] = m.group(2)
    missing = [s for s in RECEIPT_SENTENCES if s not in entries]
    assert not missing, "%s 词表缺回执译文：%s" % (lang, missing)