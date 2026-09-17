"""P0-2 / P0-3 回归：平台级端点必须只对白名单 actor 开放。

历史缺陷（2026-09-17 复核）：
    ``/v1/security`` 下 20 多个端点只要求「已登录」，于是**任何一个普通身份**
    都能：
      * ``POST /v1/security/runtime/safety-mode`` 让整个平台停摆；
      * 改安全阈值策略、走变更审批、回滚；
      * 读平台资金面、运维告警。

现在这些端点统一走 ``services/actor_guards.py`` 的运维白名单
（``ADMIN_ACTOR_IDS``），且三类角色互不隐含。
"""
from __future__ import annotations

import pytest

from config.settings import settings
from services.runtime_safety import get_runtime_safety_mode_state

OPERATOR = "ops-admin"
ARBITRATOR_ONLY = "ops-arbitrator"
PLAIN = "plain-user"

KEYS = ",".join(
    [
        OPERATOR + ":operator-secret-abcdef12",
        ARBITRATOR_ONLY + ":arbitrator-secret-abcdef12",
        PLAIN + ":plain-secret-abcdef12",
    ]
)


def _hdr(actor: str, secret: str) -> dict[str, str]:
    return {"X-Karma-Api-Key": "karma_%s_%s" % (actor, secret)}


HEADERS = {
    OPERATOR: _hdr(OPERATOR, "operator-secret-abcdef12"),
    ARBITRATOR_ONLY: _hdr(ARBITRATOR_ONLY, "arbitrator-secret-abcdef12"),
    PLAIN: _hdr(PLAIN, "plain-secret-abcdef12"),
}


@pytest.fixture
def ops_keys(monkeypatch):
    """两把钥匙：一把运维、一把只做仲裁、一把普通用户。"""
    monkeypatch.setattr(settings, "auth_api_keys", KEYS)
    monkeypatch.setattr(settings, "admin_actor_ids", OPERATOR)
    monkeypatch.setattr(settings, "arbitrator_actor_ids", ARBITRATOR_ONLY)
    monkeypatch.setattr(settings, "governance_verifier_ids", "")
    return HEADERS


# ---------------------------------------------------------------------------
# 停摆开关：普通身份绝对不能碰
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plain_actor_cannot_engage_global_safety_mode(client, ops_keys):
    resp = await client.post(
        "/v1/security/runtime/safety-mode",
        json={"enabled": True, "reason": "普通用户试图停摆平台"},
        headers=ops_keys[PLAIN],
    )
    assert resp.status_code == 403, resp.text
    # 关键断言：不只是被拒，全局状态也必须没被改过。
    assert get_runtime_safety_mode_state().enabled is False


@pytest.mark.asyncio
async def test_arbitrator_actor_cannot_engage_global_safety_mode(client, ops_keys):
    """仲裁员 ≠ 管理员：角色必须分离，不允许一把钥匙通吃。"""
    resp = await client.post(
        "/v1/security/runtime/safety-mode",
        json={"enabled": True},
        headers=ops_keys[ARBITRATOR_ONLY],
    )
    assert resp.status_code == 403, resp.text
    assert get_runtime_safety_mode_state().enabled is False


@pytest.mark.asyncio
async def test_whitelisted_admin_can_engage_and_release_safety_mode(client, ops_keys):
    on = await client.post(
        "/v1/security/runtime/safety-mode",
        json={"enabled": True, "reason": "operator drill"},
        headers=ops_keys[OPERATOR],
    )
    assert on.status_code == 200, on.text
    assert get_runtime_safety_mode_state().enabled is True

    off = await client.post(
        "/v1/security/runtime/safety-mode",
        json={"enabled": False, "reason": "drill over"},
        headers=ops_keys[OPERATOR],
    )
    assert off.status_code == 200, off.text
    assert get_runtime_safety_mode_state().enabled is False


# ---------------------------------------------------------------------------
# 平台资金面 / 运维告警：不能给普通身份看
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_funds_overview_is_admin_only(client, ops_keys):
    denied = await client.get("/v1/security/funds-overview", headers=ops_keys[PLAIN])
    assert denied.status_code == 403, denied.text

    allowed = await client.get("/v1/security/funds-overview", headers=ops_keys[OPERATOR])
    assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
async def test_ops_alerts_is_admin_only(client, ops_keys):
    denied = await client.get("/v1/security/ops/alerts", headers=ops_keys[PLAIN])
    assert denied.status_code == 403, denied.text

    allowed = await client.get("/v1/security/ops/alerts", headers=ops_keys[OPERATOR])
    assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
async def test_security_policy_writes_are_admin_only(client, ops_keys):
    body = {"config": {"failed_auth_threshold": 9}, "note": "probe", "rollout_percent": 100}
    denied = await client.post("/v1/security/policies", json=body, headers=ops_keys[PLAIN])
    assert denied.status_code == 403, denied.text

    allowed = await client.post("/v1/security/policies", json=body, headers=ops_keys[OPERATOR])
    assert allowed.status_code == 201, allowed.text


@pytest.mark.asyncio
async def test_anchor_audit_is_admin_only(client, ops_keys):
    denied = await client.post("/v1/security/runtime/anchor-audit", headers=ops_keys[PLAIN])
    assert denied.status_code == 403, denied.text

    allowed = await client.post("/v1/security/runtime/anchor-audit", headers=ops_keys[OPERATOR])
    assert allowed.status_code == 200, allowed.text


# ---------------------------------------------------------------------------
# 兼容性：控制台读的「只读状态」不能被顺手锁死
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_console_can_still_read_safety_mode(client, ops_keys):
    """操作台首页只读这一条（apps/console/scripts/karma-public-api.js），必须保持可用。"""
    resp = await client.get("/v1/security/runtime/safety-mode", headers=ops_keys[PLAIN])
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_anonymous_is_still_rejected(client, ops_keys):
    resp = await client.post("/v1/security/runtime/safety-mode", json={"enabled": True})
    assert resp.status_code == 401, resp.text
