"""
Karma — Identity Role Profile (P1/P2/P3) integration tests.

Covers the "one card → many role profiles" feature: profile CRUD + visibility
defaults, authorized disclosure (private ledger), and KYC state machine.
Ownership is exercised via the dev ``X-Karma-Identity-Id`` fallback (auth off).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import SettlementModel

OWNER = {"X-Karma-Identity-Id": "owner-1"}
PARTY = {"X-Karma-Identity-Id": "party-x"}
STRANGER = {"X-Karma-Identity-Id": "stranger"}


async def _create_profile(client: AsyncClient, *, class_: str, owner: str = "owner-1") -> dict:
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": owner, "class": class_, "display_name": "p-" + class_},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Profile CRUD + visibility defaults
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

    r = await client.get("/v1/identity/role-profiles?owner_identity_id=owner-1")
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = await client.get(f"/v1/identity/role-profiles/{p['profile_id']}")
    assert r.status_code == 200
    assert r.json()["profile_id"] == p["profile_id"]

    r = await client.put(
        f"/v1/identity/role-profiles/{p['profile_id']}",
        json={"display_name": "renamed", "kyc_status": "pending"},
    )
    assert r.status_code == 200
    assert r.json()["display_name"] == "renamed"
    assert r.json()["kyc_status"] == "pending"


@pytest.mark.asyncio
async def test_invalid_class_rejected(client: AsyncClient):
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": "owner-1", "class": "hacker"},
    )
    assert r.status_code == 422


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

    # owner can view (empty ledger)
    r = await client.get(f"/v1/identity/role-profiles/{pid}/ledger", headers=OWNER)
    assert r.status_code == 200

    # stranger is denied
    r = await client.get(f"/v1/identity/role-profiles/{pid}/ledger", headers=STRANGER)
    assert r.status_code == 403

    # grant a whole-ledger disclosure, then party can view
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

    # seed two settlements: one in-profile, one belonging to another profile
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

    # disclose only task-owned to party-x
    await client.post(
        f"/v1/identity/role-profiles/{pid}/disclosures",
        json={"authorized_identity_id": "party-x", "task_id": "task-owned", "scope": "transaction"},
        headers=OWNER,
    )

    # owner sees both in-profile rows (only task-owned has profile_id == pid)
    r = await client.get(f"/v1/identity/role-profiles/{pid}/ledger", headers=OWNER)
    assert r.status_code == 200
    assert {t["task_id"] for t in r.json()["transactions"]} == {"task-owned"}

    # authorized party sees only the disclosed task
    r = await client.get(f"/v1/identity/role-profiles/{pid}/ledger", headers=PARTY)
    assert r.status_code == 200
    assert {t["task_id"] for t in r.json()["transactions"]} == {"task-owned"}


# ---------------------------------------------------------------------------
# KYC state machine
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

    # verifier approves
    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc/verify",
        json={"decision": "verified"},
        headers={"X-Karma-Identity-Id": "verifier-1"},
    )
    assert r.status_code == 200
    assert r.json()["kyc_status"] == "verified"
    assert r.json()["kyc_payload"]["verification"]["decision"] == "verified"


@pytest.mark.asyncio
async def test_kyc_invalid_transition(client: AsyncClient):
    p = await _create_profile(client, class_="merchant")
    pid = p["profile_id"]

    # verify from none is invalid (must submit first)
    r = await client.post(
        f"/v1/identity/role-profiles/{pid}/kyc/verify",
        json={"decision": "verified"},
        headers={"X-Karma-Identity-Id": "verifier-1"},
    )
    assert r.status_code == 409
