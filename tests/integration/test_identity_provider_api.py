"""主身份认证接第三方实名 / 活体服务：端到端（含真签名）。

这条链路是「用户点一下 → 服务商核验 → 回调自动置位」的骨架。测试里用 mock 服务商，
但**签名是真的**：本地模拟走的验签代码和线上收到阿里云 / 腾讯云 / Persona 回调时是同一条。

必须守住的线：
- 没接服务商 / 密钥没配齐 → 明确报错，绝不静默放行成「已认证」；
- 签名不对 / 时间戳过期 → 401，而且一个字段都不写；
- 回调必须对得上我们**开出去的那次会话**，对不上就 409；
- 重复回调不重复置位（幂等）；
- 回调报文里的姓名 / 图片一律不落库，只留 SHA-256 指纹。
"""
from __future__ import annotations

import json
import time

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import IdentityVerificationModel
from services.identity_provider.signature import sign_timestamped_hmac

OWNER = "kid_provider_owner"
OTHER = "kid_provider_other"
SECRET = "integration-callback-secret"
BASE = "https://karma.example"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_provider_rows(db_session: AsyncSession):
    """这条链路的服务层会**真的 commit**（生产里就该这样），所以用例之间要自己清干净。

    只删本文件用的那批身份（kid_prov*），不动别的用例的数据。
    """
    yield
    await db_session.execute(
        delete(IdentityVerificationModel).where(
            IdentityVerificationModel.identity_id.like("kid_prov%")
        )
    )
    await db_session.commit()


@pytest.fixture
def provider_env(monkeypatch):
    """接上 mock 服务商（非生产环境），并把公网回调地址配上。"""
    monkeypatch.setattr(settings, "identity_provider", "mock")
    monkeypatch.setattr(settings, "identity_provider_callback_secret", SECRET)
    monkeypatch.setattr(settings, "identity_provider_public_base_url", BASE)
    monkeypatch.setattr(settings, "app_env", "test")
    return settings


def _h(identity_id: str) -> dict[str, str]:
    return {"X-Karma-Identity-Id": identity_id}


def _signed(body: dict, *, secret: str = SECRET, timestamp: int | None = None) -> tuple[bytes, dict]:
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    header = sign_timestamped_hmac(secret=secret, raw_body=raw, timestamp=timestamp)
    return raw, {"X-Karma-Provider-Signature": header}


async def _open_session(client: AsyncClient, identity_id: str = OWNER) -> dict:
    r = await client.post(
        f"/v1/identity/{identity_id}/verification/provider/session", json={}, headers=_h(identity_id)
    )
    assert r.status_code == 200, r.text
    return r.json()["session"]


async def _callback(client: AsyncClient, identity_id: str, body: dict, *, secret: str = SECRET, timestamp=None):
    raw, headers = _signed(body, secret=secret, timestamp=timestamp)
    return await client.post(
        f"/v1/identity/{identity_id}/verification/provider-callback/mock",
        content=raw,
        headers={**headers, "Content-Type": "application/json"},
    )


# --------------------------------------------------------------------------- 没接服务商


@pytest.mark.asyncio
async def test_without_a_provider_the_console_is_told_to_use_manual_review(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "identity_provider", "none")
    r = await client.get(f"/v1/identity/{OWNER}/verification/provider", headers=_h(OWNER))
    assert r.status_code == 200
    body = r.json()
    assert body["provider"]["provider"] == "none"
    assert body["provider"]["configured"] is False
    assert "复核台" in body["provider"]["note"]


@pytest.mark.asyncio
async def test_opening_a_session_without_a_provider_is_refused(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "identity_provider", "none")
    r = await client.post(
        f"/v1/identity/{OWNER}/verification/provider/session", json={}, headers=_h(OWNER)
    )
    assert r.status_code == 409
    assert "no real-name/liveness provider" in r.json()["detail"]


@pytest.mark.asyncio
async def test_half_configured_provider_says_exactly_what_is_missing(client: AsyncClient, provider_env, monkeypatch):
    monkeypatch.setattr(settings, "identity_provider_callback_secret", "")
    r = await client.post(
        f"/v1/identity/{OWNER}/verification/provider/session", json={}, headers=_h(OWNER)
    )
    assert r.status_code == 503
    assert "IDENTITY_PROVIDER_CALLBACK_SECRET" in r.json()["detail"]


@pytest.mark.asyncio
async def test_callback_without_public_base_url_is_refused(client: AsyncClient, provider_env, monkeypatch):
    monkeypatch.setattr(settings, "identity_provider_public_base_url", "")
    r = await client.post(
        f"/v1/identity/{OWNER}/verification/provider/session", json={}, headers=_h(OWNER)
    )
    assert r.status_code == 503
    assert "IDENTITY_PROVIDER_PUBLIC_BASE_URL" in r.json()["detail"]


# --------------------------------------------------------------------------- 主流程


@pytest.mark.asyncio
async def test_full_flow_callback_activates_the_identity(
    client: AsyncClient, db_session: AsyncSession, provider_env
):
    created = await _open_session(client)
    session_id = created["session_id"]
    assert created["callback_url"] == f"{BASE}/v1/identity/{OWNER}/verification/provider-callback/mock"
    assert created["mode"] == "callback"

    # 回调前：还没认证，也没激活
    r = await client.get(f"/v1/identity/{OWNER}/verification", headers=_h(OWNER))
    assert r.json()["status"] == "none"

    resp = await _callback(
        client,
        OWNER,
        {"session_id": session_id, "identity_id": OWNER, "outcome": "verified", "reason_code": "OK"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"] is True
    assert resp.json()["status"] == "verified"

    # 置位之后：本人视图、激活状态、以及审计里的盖章人
    r = await client.get(f"/v1/identity/{OWNER}/verification", headers=_h(OWNER))
    body = r.json()
    assert body["status"] == "verified"
    assert body["verified_at"]
    assert body["reviewer_identity_id"].startswith("platform:identity-provider:")
    assert "provider=mock" in body["review_note"]

    r = await client.get(f"/v1/identity/{OWNER}/activation")
    assert r.json()["activated"] is True
    assert r.json()["status"] == "verified"

    row = await db_session.get(IdentityVerificationModel, OWNER)
    await db_session.refresh(row)
    assert row.provider["active"]["status"] == "completed"
    assert row.provider["events"][-1]["event"] == "decision_applied"


@pytest.mark.asyncio
async def test_callback_is_idempotent(client: AsyncClient, provider_env):
    created = await _open_session(client)
    body = {"session_id": created["session_id"], "identity_id": OWNER, "outcome": "verified"}
    first = await _callback(client, OWNER, body)
    second = await _callback(client, OWNER, body)
    assert first.json()["applied"] is True
    assert second.status_code == 200
    assert second.json()["applied"] is False
    assert second.json()["reason"] == "already_verified"
    assert second.json()["status"] == "verified"


@pytest.mark.asyncio
async def test_rejection_is_recorded_but_not_as_a_pass(client: AsyncClient, provider_env):
    created = await _open_session(client)
    resp = await _callback(
        client,
        OWNER,
        {
            "session_id": created["session_id"],
            "identity_id": OWNER,
            "outcome": "rejected",
            "reason_code": "FACE_MISMATCH",
        },
    )
    assert resp.json()["applied"] is True
    assert resp.json()["status"] == "rejected"
    assert resp.json()["verified_at"] is None

    r = await client.get(f"/v1/identity/{OWNER}/activation")
    assert r.json()["activated"] is False

    r = await client.get(f"/v1/identity/{OWNER}/verification", headers=_h(OWNER))
    assert "FACE_MISMATCH" in r.json()["review_note"]


@pytest.mark.asyncio
async def test_rejected_identity_can_redo_the_provider_check(client: AsyncClient, provider_env):
    first = await _open_session(client)
    await _callback(
        client, OWNER, {"session_id": first["session_id"], "identity_id": OWNER, "outcome": "rejected"}
    )
    second = await _open_session(client)
    resp = await _callback(
        client, OWNER, {"session_id": second["session_id"], "identity_id": OWNER, "outcome": "verified"}
    )
    assert resp.json()["applied"] is True
    assert resp.json()["status"] == "verified"


@pytest.mark.asyncio
async def test_pending_decision_does_not_move_the_status(client: AsyncClient, provider_env):
    created = await _open_session(client)
    resp = await _callback(
        client, OWNER, {"session_id": created["session_id"], "identity_id": OWNER, "outcome": "pending"}
    )
    assert resp.json()["applied"] is False
    assert resp.json()["reason"] == "provider_still_processing"
    assert resp.json()["status"] == "none"


# --------------------------------------------------------------------------- 签名与绑定


@pytest.mark.asyncio
async def test_wrong_signature_is_rejected_and_writes_nothing(
    client: AsyncClient, db_session: AsyncSession, provider_env
):
    created = await _open_session(client)
    resp = await _callback(
        client,
        OWNER,
        {"session_id": created["session_id"], "identity_id": OWNER, "outcome": "verified"},
        secret="not-our-secret",
    )
    assert resp.status_code == 401
    row = await db_session.get(IdentityVerificationModel, OWNER)
    await db_session.refresh(row)
    assert row.status == "none"
    events = [e["event"] for e in row.provider["events"]]
    assert "decision_applied" not in events


@pytest.mark.asyncio
async def test_missing_signature_header_is_rejected(client: AsyncClient, provider_env):
    created = await _open_session(client)
    raw = json.dumps({"session_id": created["session_id"], "outcome": "verified"}).encode()
    resp = await client.post(
        f"/v1/identity/{OWNER}/verification/provider-callback/mock",
        content=raw,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_replayed_old_callback_is_rejected(client: AsyncClient, provider_env):
    created = await _open_session(client)
    stale = int(time.time()) - 3600
    resp = await _callback(
        client,
        OWNER,
        {"session_id": created["session_id"], "identity_id": OWNER, "outcome": "verified"},
        timestamp=stale,
    )
    assert resp.status_code == 401
    assert "tolerance window" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_callback_must_reference_a_session_we_issued(client: AsyncClient, provider_env):
    await _open_session(client)
    resp = await _callback(
        client, OWNER, {"session_id": "not-a-session-we-made", "identity_id": OWNER, "outcome": "verified"}
    )
    assert resp.status_code == 409
    assert "unknown verification session" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_callback_cannot_activate_a_different_identity(client: AsyncClient, provider_env):
    created = await _open_session(client, OWNER)
    # 把 OWNER 的会话号拿去给 OTHER 置位。OTHER 从没开过会话：
    # 连核验记录都没有 → 404；有记录但没有这个会话 → 409。两种都必须挡住。
    resp = await _callback(
        client, OTHER, {"session_id": created["session_id"], "identity_id": OTHER, "outcome": "verified"}
    )
    assert resp.status_code in (404, 409), resp.text

    r = await client.get(f"/v1/identity/{OTHER}/verification", headers=_h(OTHER))
    assert r.json()["status"] == "none"


@pytest.mark.asyncio
async def test_callback_for_an_identity_that_never_started_anything(client: AsyncClient, provider_env):
    resp = await _callback(
        client, OTHER, {"session_id": "x", "identity_id": OTHER, "outcome": "verified"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_callback_with_unknown_provider_name_is_refused(client: AsyncClient, provider_env):
    raw, headers = _signed({"session_id": "s", "outcome": "verified"})
    resp = await client.post(
        f"/v1/identity/{OWNER}/verification/provider-callback/notaprovider",
        content=raw,
        headers=headers,
    )
    assert resp.status_code == 409


# --------------------------------------------------------------------------- 隐私


@pytest.mark.asyncio
async def test_pii_in_the_callback_body_is_never_persisted(
    client: AsyncClient, db_session: AsyncSession, provider_env
):
    """服务商报文里常带姓名 / 证件号 / 图片。我们只白名单提取，其余一律丢弃。"""
    created = await _open_session(client)
    raw_body = {
        "session_id": created["session_id"],
        "identity_id": OWNER,
        "outcome": "verified",
        "name": "张三",
        "id_number": "110101199001011234",
        "photo": "data:image/jpeg;base64," + "A" * 4000,
    }
    raw, headers = _signed(raw_body)
    resp = await client.post(
        f"/v1/identity/{OWNER}/verification/provider-callback/mock",
        content=raw,
        headers={**headers, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    row = await db_session.get(IdentityVerificationModel, OWNER)
    await db_session.refresh(row)
    stored = json.dumps(row.provider, ensure_ascii=False) + json.dumps(row.review_note or "")
    for leak in ("张三", "110101199001011234", "AAAA"):
        assert leak not in stored
    # 指纹留下（可回溯「当时收到的是哪一份报文」），原文不留
    assert row.provider["events"][-1]["detail"]["raw_digest"]


# --------------------------------------------------------------------------- 权限 / 本地通道


@pytest.mark.asyncio
async def test_only_the_owner_can_open_a_session(client: AsyncClient, provider_env):
    r = await client.post(
        f"/v1/identity/{OWNER}/verification/provider/session", json={}, headers=_h(OTHER)
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_return_url_cannot_redirect_anywhere(client: AsyncClient, provider_env):
    r = await client.post(
        f"/v1/identity/{OWNER}/verification/provider/session",
        json={"return_url": "https://evil.example/steal"},
        headers=_h(OWNER),
    )
    assert r.status_code == 400
    r = await client.post(
        f"/v1/identity/{OWNER}/verification/provider/session",
        json={"return_url": BASE + "/console/"},
        headers=_h(OWNER),
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_mock_push_channel_is_invisible_in_production(client: AsyncClient, provider_env, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    r = await client.post(
        f"/v1/identity/{OWNER}/verification/provider/mock-push",
        json={"outcome": "verified"},
        headers=_h(OWNER),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_mock_push_channel_works_locally_and_goes_through_signature_verification(
    client: AsyncClient, provider_env
):
    await _open_session(client)
    r = await client.post(
        f"/v1/identity/{OWNER}/verification/provider/mock-push",
        json={"outcome": "verified"},
        headers=_h(OWNER),
    )
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is True
    assert r.json()["status"] == "verified"
