"""
Karma — Identity Role Profile (P1/P2/P3) integration tests.

Covers the "one card → many role profiles" feature: profile CRUD + visibility
defaults + ownership enforcement, authorized disclosure (private ledger), and
KYC state machine (with verifier-gated verification).
Ownership is exercised via the dev ``X-Karma-Identity-Id`` fallback (auth off).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import SettlementModel

OWNER = {"X-Karma-Identity-Id": "owner-1"}
PARTY = {"X-Karma-Identity-Id": "party-x"}
STRANGER = {"X-Karma-Identity-Id": "stranger"}
VERIFIER = {"X-Karma-Identity-Id": "verifier-1"}


@pytest.fixture(autouse=True)
def _allow_governance_roles(monkeypatch):
    """verifier / arbitrator 默认不许自助开通（防自助提权）。

    这个文件测的是角色档案本身，所以把用到的身份放进运维白名单；
    「不给白名单就必须 403」这件事在 tests/integration/test_developer_api.py 覆盖。
    """
    monkeypatch.setattr(settings, "governance_verifier_ids", "verifier-1,owner-1")


async def _create_profile(client: AsyncClient, *, class_: str, owner: str = "owner-1") -> dict:
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": owner, "class": class_, "display_name": "p-" + class_},
        headers={"X-Karma-Identity-Id": owner},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Profile CRUD + visibility defaults + ownership enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enterprise_defaults_private(client: AsyncClient):
    p = await _create_profile(client, class_="enterprise")
    assert p["class"] == "enterprise"
    assert p["visibility"] == "private"


@pytest.mark.asyncio
async def test_non_enterprise_defaults_public(client: AsyncClient):
    for cls in ("individual", "merchant", "verifier", "arbitrator"):
        p = await _create_profile(client, class_=cls)
        assert p["visibility"] == "public", cls


@pytest.mark.asyncio
async def test_profile_list_get_update(client: AsyncClient):
    p = await _create_profile(client, class_="individual")

    r = await client.get("/v1/identity/role-profiles?owner_identity_id=owner-1", headers=OWNER)
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = await client.get(f"/v1/identity/role-profiles/{p['profile_id']}", headers=OWNER)
    assert r.status_code == 200
    assert r.json()["profile_id"] == p["profile_id"]
    assert "kyc_payload" in r.json()  # owner sees full payload

    r = await client.put(
        f"/v1/identity/role-profiles/{p['profile_id']}",
        json={"display_name": "renamed"},
        headers=OWNER,
    )
    assert r.status_code == 200
    assert r.json()["display_name"] == "renamed"


@pytest.mark.asyncio
async def test_invalid_class_rejected(client: AsyncClient):
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": "owner-1", "class": "hacker"},
        headers=OWNER,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_requires_matching_owner(client: AsyncClient):
    # caller claims a different owner → 403
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": "someone-else", "class": "individual"},
        headers=OWNER,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_update_requires_owner(client: AsyncClient):
    p = await _create_profile(client, class_="individual")
    r = await client.put(
        f"/v1/identity/role-profiles/{p['profile_id']}",
        json={"display_name": "hijacked"},
        headers=STRANGER,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_anonymous_list_only_public_redacted(client: AsyncClient):
    await _create_profile(client, class_="enterprise")  # private
    await _create_profile(client, class_="individual")  # public

    # anonymous (no auth) list → only public, and kyc_payload redacted
    r = await client.get("/v1/identity/role-profiles")
    assert r.status_code == 200
    profiles = r.json()["profiles"]
    assert all(p["visibility"] == "public" for p in profiles)
    assert all("kyc_payload" not in p for p in profiles)


@pytest.mark.asyncio
async def test_private_get_hidden_from_stranger(client: AsyncClient):
    p = await _create_profile(client, class_="enterprise")  # private
    r = await client.get(f"/v1/identity/role-profiles/{p['profile_id']}", headers=STRANGER)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Authorized disclosure + private ledger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disclosure_grant_list_revoke(client: AsyncClient):
    p = await _create_profile(client, class_="enterprise")
    pid = p["profile_id"]

    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/disclosures",
        json={"authorized_identity_id": "party-x", "task_id": "t1", "scope": "transaction"},
        headers=OWNER,
    )
    assert r.status_code == 201, r.text
    did = r.json()["disclosure_id"]

    r = await client.get(f"/v1/identity/role-profiles/{pid}/disclosures", headers=OWNER)
    assert r.status_code == 200
    assert r.json()["disclosures"][0]["authorized_identity_id"] == "party-x"

    r = await client.delete(f"/v1/identity/role-profiles/{pid}/disclosures/{did}", headers=OWNER)
    assert r.status_code == 200
    assert r.json()["status"] == "revoked"


@pytest.mark.asyncio
async def test_disclosure_requires_owner(client: AsyncClient):
    p = await _create_profile(client, class_="enterprise")
    r = await client.post(
        f"/v1/identity/role-profiles/{p['profile_id']}/disclosures",
        json={"authorized_identity_id": "party-x", "task_id": "t1"},
        headers=STRANGER,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_transaction_disclosure_requires_task_id(client: AsyncClient):
    p = await _create_profile(client, class_="enterprise")
    r = await client.post(
        f"/v1/identity/role-profiles/{p['profile_id']}/disclosures",
        json={"authorized_identity_id": "party-x", "scope": "transaction"},
        headers=OWNER,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_private_ledger_authorization(client: AsyncClient):
    p = await _create_profile(client, class_="enterprise")
    pid = p["profile_id"]

    r = await client.get(f"/v1/identity/role-profiles/{pid}/ledger", headers=OWNER)
    assert r.status_code == 200

    r = await client.get(f"/v1/identity/role-profiles/{pid}/ledger", headers=STRANGER)
    assert r.status_code == 403

    await client.post(
        f"/v1/identity/role-profiles/{pid}/disclosures",
        json={"authorized_identity_id": "party-x", "scope": "ledger"},
        headers=OWNER,
    )
    r = await client.get(f"/v1/identity/role-profiles/{pid}/ledger", headers=PARTY)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_ledger_filters_by_disclosed_task(
    client: AsyncClient, db_session: AsyncSession
):
    p = await _create_profile(client, class_="enterprise")
    pid = p["profile_id"]

    db_session.add(
        SettlementModel(
            task_id="task-owned", profile_id=pid, escrow_amount=10.0, currency="USD",
            status="draft", client_agent_id="owner-1",
        )
    )
    db_session.add(
        SettlementModel(
            task_id="task-other", profile_id="other-profile", escrow_amount=20.0, currency="USD",
            status="draft", client_agent_id="owner-1",
        )
    )
    await db_session.commit()

    await client.post(
        f"/v1/identity/role-profiles/{pid}/disclosures",
        json={"authorized_identity_id": "party-x", "task_id": "task-owned", "scope": "transaction"},
        headers=OWNER,
    )

    r = await client.get(f"/v1/identity/role-profiles/{pid}/ledger", headers=OWNER)
    assert r.status_code == 200
    assert {t["task_id"] for t in r.json()["transactions"]} == {"task-owned"}

    r = await client.get(f"/v1/identity/role-profiles/{pid}/ledger", headers=PARTY)
    assert r.status_code == 200
    assert {t["task_id"] for t in r.json()["transactions"]} == {"task-owned"}


# ---------------------------------------------------------------------------
# KYC state machine (verifier-gated)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kyc_full_flow(client: AsyncClient):
    p = await _create_profile(client, class_="merchant")
    pid = p["profile_id"]

    r = await client.post(f"/v1/identity/role-profiles/{pid}/kyc", json={"kyc_payload": {"doc": "passport"}}, headers=OWNER)
    assert r.status_code == 200
    assert r.json()["kyc_status"] == "pending"

    # owner cannot self-verify
    r = await client.post(f"/v1/identity/role-profiles/{pid}/kyc/verify", json={"decision": "verified"}, headers=OWNER)
    assert r.status_code == 403

    # non-verifier cannot verify
    r = await client.post(f"/v1/identity/role-profiles/{pid}/kyc/verify", json={"decision": "verified"}, headers=STRANGER)
    assert r.status_code == 403

    # a verifier-class profile can approve
    await _create_profile(client, class_="verifier", owner="verifier-1")
    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc/verify",
        json={"decision": "verified"},
        headers=VERIFIER,
    )
    assert r.status_code == 200
    assert r.json()["kyc_status"] == "verified"
    assert r.json()["kyc_payload"]["verification"]["decision"] == "verified"


@pytest.mark.asyncio
async def test_kyc_invalid_transition(client: AsyncClient):
    p = await _create_profile(client, class_="merchant")
    pid = p["profile_id"]

    await _create_profile(client, class_="verifier", owner="verifier-1")

    # verify from none is invalid (must submit first) → 409
    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc/verify",
        json={"decision": "verified"},
        headers=VERIFIER,
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# 个体助理认证（操作台「身份 · 认证 → 个体助理认证」）
# ---------------------------------------------------------------------------


def _sole_payload(**over) -> dict:
    payload = {
        "kind": "sole_proprietor",
        "consent": True,
        "business_name": "张三小吃店",
        "operator_name": "张三",
        "registration_no": "92330100MA2ABCDE12",
        "region": "浙江省杭州市西湖区",
        "business_scope": "餐饮服务；预包装食品销售",
        "main_products": "手冲咖啡豆、门店自提",
        "business_address": "杭州市西湖区文三路 1 号",
        "contact_phone": "13800000000",
        "contact_email": "zhangsan@example.com",
        "docs": [{"kind": "BUSINESS_LICENSE", "name": "营业执照（副本）", "digest": "a" * 64}],
        "doc_digest": "b" * 64,
        "package_digest": "c" * 64,
        "package_cipher": "Q0lQSEVSVEVYVA" * 8,
        "encryption": {
            "algo": "AES-GCM-256",
            "kdf": "PBKDF2-SHA256",
            "iterations": 250000,
            "salt_b64": "c2FsdHNhbHRzYWx0c2FsdA==",
            "iv_b64": "aXZpdml2aXZpdg==",
            "key_wrap": "wallet-signature-v1",
        },
    }
    payload.update(over)
    return payload


@pytest.mark.asyncio
async def test_sole_proprietor_certification_payload_is_accepted(client: AsyncClient):
    """操作台个体认证页提交的载荷形状要能被服务端照收：
    声明字段（经营范围 / 主营产品 / 经营地址）+ 资质清单 + 密文包，一个都不能在路上掉。"""
    p = await _create_profile(client, class_="merchant")
    pid = p["profile_id"]

    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc",
        json={"kyc_payload": _sole_payload()},
        headers=OWNER,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kyc_status"] == "pending"
    stored = body["kyc_payload"]
    assert stored["kind"] == "sole_proprietor"
    assert stored["business_scope"] == "餐饮服务；预包装食品销售"
    assert stored["main_products"] == "手冲咖啡豆、门店自提"
    assert stored["business_address"] == "杭州市西湖区文三路 1 号"
    assert stored["docs"][0]["kind"] == "BUSINESS_LICENSE"
    assert stored["package_cipher"] == "Q0lQSEVSVEVYVA" * 8


@pytest.mark.asyncio
async def test_sole_proprietor_certification_still_rejects_plaintext_originals(client: AsyncClient):
    """声明字段放开了，红线没放开：营业执照原图 / 证件明文照旧 400。

    三种夹带方式各测一次，因为判定本来就是三条不同的规则：
    1) 键名直接叫 image / 照片；
    2) 值是个 data URL；
    3) 换了键名、值是一整块裸 base64（原地换层皮）。
    """
    p = await _create_profile(client, class_="merchant")
    pid = p["profile_id"]

    async def submit(payload):
        return await client.post(
            f"/v1/identity/role-profiles/{pid}/kyc",
            json={"kyc_payload": payload},
            headers=OWNER,
        )

    r = await submit(_sole_payload(image="x"))
    assert r.status_code == 400 and "image" in r.json()["detail"], r.text

    r = await submit(_sole_payload(photo="data:image/png;base64,AAAA"))
    assert r.status_code == 400, r.text

    r = await submit(_sole_payload(docs=[{"kind": "BUSINESS_LICENSE", "name": "营业执照", "b64": "A" * 5000}]))
    assert r.status_code == 400 and "base64" in r.json()["detail"], r.text

    # 全程被拒，状态没被推着往前走
    row = await client.get(f"/v1/identity/role-profiles/{pid}", headers=OWNER)
    assert row.json()["kyc_status"] == "none"
