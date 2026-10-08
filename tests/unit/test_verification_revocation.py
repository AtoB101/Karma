# -*- coding: utf-8 -*-
"""合规撤销（审计 O4）：verified 是认证终态，唯一出口是这条边，闸门更严。

- 复核员必须两人：一人发起不算执行，**另一人**确认才生效；同一人既发起又确认 → 409；
- 运维白名单（ADMIN_ACTOR_IDS）可单人直接执行；
- 本人 / 非复核岗不能撤销；只有 verified 能撤销；理由必填；
- 撤销后对外不再显示「已验证」，且本人可以改了重交。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import (
    EntityVerificationModel,
    IdentityRoleProfile,
    VerificationRevocationRequestModel,
)
from services.security_monitoring import SecurityMonitoringEventType

DIGEST_A = "a" * 64
DIGEST_C = "c" * 64
CIPHER = "Q0lQSEVSVEVYVA" * 8
ENC = {
    "algo": "AES-GCM-256",
    "kdf": "PBKDF2-SHA256",
    "iterations": 250000,
    "salt_b64": "c2FsdHNhbHRzYWx0c2FsdA==",
    "iv_b64": "aXZpdml2aXZpdg==",
    "key_wrap": "wallet-signature-v1",
}
DOMAIN = "data-revoke.example.com"
REASON = "工商登记已注销，官网已停用（复核时递交的材料系伪造）"

VERIFIER_A = "rev-verifier-a"
VERIFIER_B = "rev-verifier-b"
OPERATOR = "rev-operator"


def _h(identity: str) -> dict:
    return {"X-Karma-Identity-Id": identity}


@pytest.fixture(autouse=True)
def _governance(monkeypatch):
    monkeypatch.setattr(settings, "governance_verifier_ids", "%s,%s" % (VERIFIER_A, VERIFIER_B))
    monkeypatch.setattr(settings, "admin_actor_ids", OPERATOR)


async def _verifier(client: AsyncClient, ident: str) -> dict:
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": ident, "class": "verifier"},
        headers=_h(ident),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _seed_entity(db_session: AsyncSession, identity_id: str, *, status: str = "verified"):
    row = EntityVerificationModel(
        identity_id=identity_id,
        status=status,
        subject_type="business",
        legal_name="示例数据科技有限公司",
        registration_no="91330100MA2ABCDE12",
        jurisdiction="CN-ZJ",
        legal_rep="张三",
        official_domain=DOMAIN,
        contact_email="ops@example.com",
        service_category="data_api",
        service_scope="交易所行情与地址风控数据接口，分钟级更新，按次计费",
        certifications=[],
        doc_digest=DIGEST_A,
        package_digest=DIGEST_C,
        package_cipher=CIPHER,
        encryption=dict(ENC),
        extracted={"consent": True},
        website_verified_at=datetime.utcnow(),
        verified_at=datetime.utcnow() if status == "verified" else None,
        reviewer_identity_id=VERIFIER_A if status == "verified" else None,
    )
    db_session.add(row)
    await db_session.commit()
    return row


async def _verified_kyc_profile(
    client: AsyncClient, db_session: AsyncSession, owner: str = "rev-owner"
) -> str:
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": owner, "class": "merchant"},
        headers=_h(owner),
    )
    assert r.status_code == 201, r.text
    pid = r.json()["profile_id"]
    row = await db_session.get(IdentityRoleProfile, pid)
    row.kyc_status = "verified"
    row.kyc_payload = {"kind": "sole_proprietor", "business_name": "张三小吃店"}
    await db_session.commit()
    return pid


async def _revoke_entity(client: AsyncClient, ident: str, identity_id: str, reason: str = REASON):
    return await client.post(
        f"/v1/identity/{identity_id}/entity-verification/revoke",
        json={"reason": reason},
        headers=_h(ident),
    )


# ---------------------------------------------------------------------------
# 主体认证
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_revoke_needs_two_verifiers(client: AsyncClient, db_session: AsyncSession):
    await _verifier(client, VERIFIER_A)
    await _seed_entity(db_session, "rev-entity-1")

    r = await _revoke_entity(client, VERIFIER_A, "rev-entity-1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revoked"] is False
    assert body["state"] == "awaiting_second_reviewer"
    assert body["requires_second_reviewer"] is True
    assert body["proposed_by"] == VERIFIER_A

    pub = await client.get("/v1/entities/rev-entity-1")
    assert pub.json()["status"] == "verified"

    r = await _revoke_entity(client, VERIFIER_A, "rev-entity-1")
    assert r.status_code == 409, r.text

    await _verifier(client, VERIFIER_B)
    r = await _revoke_entity(client, VERIFIER_B, "rev-entity-1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revoked"] is True
    assert body["path"] == "two_person"
    assert body["proposed_by"] == VERIFIER_A
    assert body["confirmed_by"] == VERIFIER_B

    pub = await client.get("/v1/entities/rev-entity-1")
    assert pub.json()["status"] == "rejected"

    row = await db_session.get(EntityVerificationModel, "rev-entity-1")
    await db_session.refresh(row)
    assert row.status == "rejected"
    assert row.verified_at is None
    assert VERIFIER_A in (row.review_note or "") and VERIFIER_B in (row.review_note or "")
    assert REASON in (row.review_note or "")


@pytest.mark.asyncio
async def test_entity_revoke_operator_single_actor(client: AsyncClient, db_session: AsyncSession):
    await _seed_entity(db_session, "rev-entity-op")
    r = await _revoke_entity(client, OPERATOR, "rev-entity-op")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revoked"] is True
    assert body["path"] == "operator"
    assert body["confirmed_by"] == OPERATOR
    pub = await client.get("/v1/entities/rev-entity-op")
    assert pub.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_entity_revoke_forbidden_for_owner_and_non_verifier(
    client: AsyncClient, db_session: AsyncSession
):
    await _seed_entity(db_session, "rev-entity-3")
    r = await _revoke_entity(client, "rev-entity-3", "rev-entity-3")
    assert r.status_code == 403, r.text
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": "rev-individual", "class": "individual"},
        headers=_h("rev-individual"),
    )
    assert r.status_code == 201, r.text
    r = await _revoke_entity(client, "rev-individual", "rev-entity-3")
    assert r.status_code == 403, r.text
    row = await db_session.get(EntityVerificationModel, "rev-entity-3")
    await db_session.refresh(row)
    assert row.status == "verified"


@pytest.mark.asyncio
async def test_entity_revoke_requires_verified_status(client: AsyncClient, db_session: AsyncSession):
    await _verifier(client, VERIFIER_A)
    await _verifier(client, VERIFIER_B)
    await _seed_entity(db_session, "rev-entity-pending", status="pending")
    r = await _revoke_entity(client, VERIFIER_A, "rev-entity-pending")
    assert r.status_code == 409, r.text
    r = await _revoke_entity(client, OPERATOR, "rev-entity-pending")
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_entity_revoke_requires_a_real_reason(client: AsyncClient, db_session: AsyncSession):
    await _verifier(client, VERIFIER_A)
    await _seed_entity(db_session, "rev-entity-reason")
    r = await _revoke_entity(client, VERIFIER_A, "rev-entity-reason", reason="假")
    assert r.status_code == 422, r.text
    row = await db_session.get(EntityVerificationModel, "rev-entity-reason")
    await db_session.refresh(row)
    assert row.status == "verified"


@pytest.mark.asyncio
async def test_revoked_entity_can_resubmit(client: AsyncClient, db_session: AsyncSession):
    await _verifier(client, VERIFIER_A)
    await _seed_entity(db_session, "rev-entity-resubmit")
    r = await _revoke_entity(client, OPERATOR, "rev-entity-resubmit")
    assert r.json()["revoked"] is True

    body = {
        "subject_type": "business",
        "legal_name": "示例数据科技有限公司",
        "registration_no": "91330100MA2ABCDE12",
        "jurisdiction": "CN-ZJ",
        "legal_rep": "张三",
        "official_domain": DOMAIN,
        "contact_email": "ops@example.com",
        "service_category": "data_api",
        "service_scope": "交易所行情与地址风控数据接口，分钟级更新，按次计费",
        "certifications": [{"kind": "BUSINESS_LICENSE", "name": "营业执照", "digest": DIGEST_A}],
        "doc_digest": DIGEST_A,
        "package_digest": DIGEST_C,
        "package_cipher": CIPHER,
        "encryption": dict(ENC),
        "extracted": {"consent": True, "legal_name": "示例数据科技有限公司"},
    }
    r = await client.post(
        "/v1/identity/rev-entity-resubmit/entity-verification/submit",
        json=body,
        headers=_h("rev-entity-resubmit"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_stale_proposal_expires(client: AsyncClient, db_session: AsyncSession):
    await _verifier(client, VERIFIER_A)
    await _verifier(client, VERIFIER_B)
    await _seed_entity(db_session, "rev-entity-stale")

    r = await _revoke_entity(client, VERIFIER_A, "rev-entity-stale")
    assert r.json()["revoked"] is False

    rows = (
        await db_session.execute(select(VerificationRevocationRequestModel))
    ).scalars().all()
    assert rows
    for row in rows:
        row.proposed_at = datetime.utcnow() - timedelta(hours=25)
    await db_session.commit()

    r = await _revoke_entity(client, VERIFIER_A, "rev-entity-stale")
    assert r.status_code == 200 and r.json()["revoked"] is False, r.text
    r = await _revoke_entity(client, VERIFIER_B, "rev-entity-stale")
    assert r.json()["revoked"] is True, r.text


# ---------------------------------------------------------------------------
# 子身份 KYC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kyc_revoke_two_verifiers(client: AsyncClient, db_session: AsyncSession):
    await _verifier(client, VERIFIER_A)
    pid = await _verified_kyc_profile(client, db_session)

    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc/revoke",
        json={"reason": REASON},
        headers=_h(VERIFIER_A),
    )
    assert r.status_code == 200, r.text
    assert r.json()["revoked"] is False
    assert r.json()["kyc_status"] == "verified"

    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc/revoke",
        json={"reason": REASON},
        headers=_h(VERIFIER_A),
    )
    assert r.status_code == 409, r.text

    await _verifier(client, VERIFIER_B)
    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc/revoke",
        json={"reason": REASON},
        headers=_h(VERIFIER_B),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revoked"] is True and body["kyc_status"] == "rejected"
    assert body["proposed_by"] == VERIFIER_A and body["confirmed_by"] == VERIFIER_B

    row = await db_session.get(IdentityRoleProfile, pid)
    await db_session.refresh(row)
    assert row.kyc_status == "rejected"
    verdict = row.kyc_payload["verification"]
    assert verdict["kind"] == "compliance_revocation"
    assert verdict["decision"] == "rejected"
    assert verdict["proposed_by"] == VERIFIER_A
    assert verdict["verified_by"] == VERIFIER_B


@pytest.mark.asyncio
async def test_kyc_revoke_operator_single_actor(client: AsyncClient, db_session: AsyncSession):
    pid = await _verified_kyc_profile(client, db_session)
    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc/revoke",
        json={"reason": REASON},
        headers=_h(OPERATOR),
    )
    assert r.status_code == 200, r.text
    assert r.json()["revoked"] is True and r.json()["path"] == "operator"


@pytest.mark.asyncio
async def test_kyc_revoke_forbidden_for_owner(client: AsyncClient, db_session: AsyncSession):
    pid = await _verified_kyc_profile(client, db_session, owner="rev-owner-self")
    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc/revoke",
        json={"reason": REASON},
        headers=_h("rev-owner-self"),
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 可撤销列表 + 安全事件
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revocable_listing_and_confirm_flag(client: AsyncClient, db_session: AsyncSession):
    await _verifier(client, VERIFIER_A)
    await _verifier(client, VERIFIER_B)
    await _seed_entity(db_session, "rev-entity-list")
    pid = await _verified_kyc_profile(client, db_session)

    r = await client.get("/v1/reviews/revocable", headers=_h(VERIFIER_A))
    assert r.status_code == 200, r.text
    ids = {(item["kind"], item["target_id"]) for item in r.json()["items"]}
    assert ("entity_verification", "rev-entity-list") in ids
    assert ("role_profile_kyc", pid) in ids

    await _revoke_entity(client, VERIFIER_A, "rev-entity-list")

    mine = await client.get("/v1/reviews/revocable", headers=_h(VERIFIER_A))
    item = next(i for i in mine.json()["items"] if i["target_id"] == "rev-entity-list")
    assert item["pending_revocation"]["proposed_by"] == VERIFIER_A
    assert item["can_confirm"] is False

    other = await client.get("/v1/reviews/revocable", headers=_h(VERIFIER_B))
    item = next(i for i in other.json()["items"] if i["target_id"] == "rev-entity-list")
    assert item["can_confirm"] is True


@pytest.mark.asyncio
async def test_revocable_listing_requires_verifier(client: AsyncClient):
    r = await client.get("/v1/reviews/revocable", headers=_h("rev-nobody"))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_revocation_emits_security_event(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    import api.routes.entity_verification as evmod

    events: list = []
    monkeypatch.setattr(evmod, "record_security_event", lambda et, **kw: events.append((et, kw)))
    await _seed_entity(db_session, "rev-entity-event")
    r = await _revoke_entity(client, OPERATOR, "rev-entity-event")
    assert r.json()["revoked"] is True
    assert len(events) == 1
    et, kw = events[0]
    assert et == SecurityMonitoringEventType.VERIFICATION_REVOKED
    assert kw["metadata"]["target_id"] == "rev-entity-event"
    assert kw["metadata"]["confirmed_by"] == OPERATOR
    assert kw["metadata"]["path"] == "operator"