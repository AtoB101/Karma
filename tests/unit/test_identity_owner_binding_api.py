"""Identity ownership binding (G1/G2/G3) —— 强制鉴权下必须 403。

盘点见 security/audit/2026-10-08-boundary-and-permission-gap-audit.md：
``/v1/identities/*``、``/v1/identity/{id}/credentials|class``、``GET /v1/capacity/{id}``
此前只要求「已登录」，``identity_id`` 取自路径、无人校验 —— 任何登录身份都能改**别人**的
自动化资金边界 / 代他人签发吊销凭证 / 读他人额度。这里把 403 钉住，并确认本人与运维岗放行。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import app
from config.settings import settings
from db.models.orm import CapacityModel
from db.session import get_db

_KEYS = "owner1:secret-owner-123456,other1:secret-other-123456"
H_OWNER = {"X-Karma-Api-Key": "karma_owner1_secret-owner-123456"}
H_OTHER = {"X-Karma-Api-Key": "karma_other1_secret-other-123456"}
H_ADMIN = {"X-Karma-Api-Key": "karma_ops-admin_secret-admin-123456"}


def _enable() -> tuple:
    saved = (
        settings.auth_enforce_protected_routes,
        settings.identity_require_owner_binding,
        settings.auth_api_keys,
        settings.admin_actor_ids,
    )
    settings.auth_enforce_protected_routes = True
    settings.identity_require_owner_binding = True
    settings.auth_api_keys = _KEYS
    settings.admin_actor_ids = ""
    return saved


def _restore(saved: tuple) -> None:
    (
        settings.auth_enforce_protected_routes,
        settings.identity_require_owner_binding,
        settings.auth_api_keys,
        settings.admin_actor_ids,
    ) = saved
    app.dependency_overrides.clear()


def _client(db_session) -> AsyncClient:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_capacity(db_session, identity_id: str) -> None:
    db_session.add(
        CapacityModel(
            identity_id=identity_id,
            total_locked_usdc=10.0,
            total_bill_credits=10.0,
            available_credits=10.0,
            reserved_credits=0.0,
            in_progress_credits=0.0,
            confirmed_progress_credits=0.0,
            disputed_credits=0.0,
            pending_settlement_credits=0.0,
            burned_credits=0.0,
            released_credits=0.0,
            updated_at=datetime.utcnow(),
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_capacity_read_rejects_cross_identity_actor(db_session):
    saved = _enable()
    try:
        await _seed_capacity(db_session, "owner1")
        async with _client(db_session) as client:
            bad = await client.get("/v1/capacity/owner1", headers=H_OTHER)
            assert bad.status_code == 403, bad.text
            ok = await client.get("/v1/capacity/owner1", headers=H_OWNER)
            assert ok.status_code == 200, ok.text
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_identity_profile_init_rejects_cross_identity_actor(db_session):
    saved = _enable()
    try:
        async with _client(db_session) as client:
            bad = await client.post("/v1/identities/owner1/profile/init", json={}, headers=H_OTHER)
            assert bad.status_code == 403, bad.text
            ok = await client.post("/v1/identities/owner1/profile/init", json={}, headers=H_OWNER)
            assert ok.status_code == 200, ok.text
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_automation_policy_put_rejects_cross_identity_actor(db_session):
    saved = _enable()
    try:
        body = {
            "auto_enabled": True,
            "single_limit": 50,
            "daily_limit": 200,
            "permissions": ["submit_receipt"],
            "high_risk_mode": "always",
            "responsibility_acknowledged": True,
        }
        async with _client(db_session) as client:
            bad = await client.put("/v1/identities/owner1/automation-policy", json=body, headers=H_OTHER)
            assert bad.status_code == 403, bad.text
            ok = await client.put("/v1/identities/owner1/automation-policy", json=body, headers=H_OWNER)
            assert ok.status_code == 200, ok.text
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_identity_card_credentials_reject_cross_identity_actor(db_session):
    saved = _enable()
    try:
        target = "kid_cross_tenant_001"
        async with _client(db_session) as client:
            bad = await client.post(
                "/v1/identity/%s/credentials" % target,
                json={"type": "email"},
                headers=H_OTHER,
            )
            assert bad.status_code == 403, bad.text
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_ops_allowlist_can_act_on_any_identity(db_session):
    saved = _enable()
    try:
        settings.admin_actor_ids = "ops-admin"
        settings.auth_api_keys = _KEYS + ",ops-admin:secret-admin-123456"
        await _seed_capacity(db_session, "owner1")
        async with _client(db_session) as client:
            ok = await client.get("/v1/capacity/owner1", headers=H_ADMIN)
            assert ok.status_code == 200, ok.text
    finally:
        _restore(saved)

@pytest.mark.asyncio
async def test_delivery_session_rejects_cross_identity_actor(db_session):
    """POD 会话由卖方发起：自报 seller_agent_id 不算，得是本人（G4）。"""
    saved = _enable()
    try:
        async with _client(db_session) as client:
            bad = await client.post(
                "/v1/delivery-verification/sessions",
                json={
                    "task_id": "task-pod-cross-001",
                    "scene_id": "physical_triple",
                    "seller_agent_id": "owner1",
                    "buyer_agent_id": "buyer1",
                },
                headers=H_OTHER,
            )
            assert bad.status_code == 403, bad.text
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_delivery_buyer_confirm_rejects_cross_identity_actor(db_session):
    """买方验收是放款闸门输入：自报 actor_agent_id 不算（G4）。"""
    saved = _enable()
    try:
        async with _client(db_session) as client:
            bad = await client.post(
                "/v1/delivery-verification/vid-cross-001/buyer-confirm",
                json={"actor_agent_id": "owner1", "confirm": True},
                headers=H_OTHER,
            )
            assert bad.status_code == 403, bad.text
    finally:
        _restore(saved)
