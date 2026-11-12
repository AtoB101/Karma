"""
Per-profile capacity allocation (P1: 每个身份在授权额度内行事).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

OWNER = {"X-Karma-Identity-Id": "owner-1"}


async def _create_profile(client: AsyncClient, class_: str = "individual") -> dict:
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": "owner-1", "class": class_, "display_name": "p"},
        headers=OWNER,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _lock(client: AsyncClient, amount: float) -> None:
    r = await client.post("/v1/capacity/owner-1/lock", json={"amount": amount}, headers=OWNER)
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_allocate_and_get(client: AsyncClient):
    p = await _create_profile(client)
    await _lock(client, 100.0)

    r = await client.put(
        "/v1/capacity/owner-1/allocations",
        json={"allocations": {p["profile_id"]: 40.0}},
        headers=OWNER,
    )
    assert r.status_code == 200, r.text
    allocs = r.json()["allocations"]
    assert allocs[0]["allocated_credits"] == 40.0
    assert allocs[0]["available_credits"] == 40.0

    r = await client.get("/v1/capacity/owner-1/allocations", headers=OWNER)
    assert r.status_code == 200
    assert r.json()["allocations"][0]["profile_id"] == p["profile_id"]


@pytest.mark.asyncio
async def test_over_allocate_rejected(client: AsyncClient):
    p = await _create_profile(client)
    await _lock(client, 100.0)

    r = await client.put(
        "/v1/capacity/owner-1/allocations",
        json={"allocations": {p["profile_id"]: 150.0}},
        headers=OWNER,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_allocate_requires_owner(client: AsyncClient):
    p = await _create_profile(client)
    await _lock(client, 100.0)

    r = await client.put(
        "/v1/capacity/owner-1/allocations",
        json={"allocations": {p["profile_id"]: 40.0}},
        headers={"X-Karma-Identity-Id": "stranger"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_voucher_enforced_by_profile_quota(client: AsyncClient):
    """Buyer 以某档案下单，金额超过该档案授权额度 -> 409."""
    p = await _create_profile(client, class_="merchant")
    await _lock(client, 100.0)
    await client.put(
        "/v1/capacity/owner-1/allocations",
        json={"allocations": {p["profile_id"]: 20.0}},
        headers=OWNER,
    )

    from datetime import datetime, timedelta

    h = "aa" * 32
    exp = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    r = await client.post(
        "/v1/vouchers",
        json={
            "buyer_identity_id": "owner-1",
            "seller_identity_id": "seller-1",
            "amount": 30.0,
            "bill_credit_amount": 30.0,
            "task_type": "e2e.profile.quota",
            "task_description_hash": h,
            "progress_rule_hash": h,
            "evidence_requirement_hash": h,
            "expiry_time": exp,
            "nonce": "quota-nonce",
            "buyer_signature": "0x" + "11" * 65,
            "currency": "USDC",
            "profile_id": p["profile_id"],
        },
    )
    assert r.status_code == 409, r.text
    assert "profile credits" in r.json().get("detail", "")


@pytest.mark.asyncio
async def test_release_profile_credits_after_spend(client: AsyncClient, db_session):
    """spend 冻结后 release 释放：in_progress 回落到 released/available。"""
    from services.profile_capacity import release_profile_credits, spend_profile_credits

    p = await _create_profile(client)
    await _lock(client, 100.0)
    await client.put(
        "/v1/capacity/owner-1/allocations",
        json={"allocations": {p["profile_id"]: 50.0}},
        headers=OWNER,
    )

    await spend_profile_credits(db_session, profile_id=p["profile_id"], amount=30.0)

    row = await release_profile_credits(
        db_session, profile_id=p["profile_id"], settled_amount=30.0, refunded_amount=0.0
    )
    assert row is not None
    assert row.in_progress_credits == 0.0
    assert row.released_credits == 30.0
    assert row.available_credits == 20.0


@pytest.mark.asyncio
async def test_record_profile_settlement_outcome(client: AsyncClient, db_session):
    """结算后回写档案声誉：successful_tasks +1、score 上升。"""
    from services.identity_reputation import record_profile_settlement_outcome

    p = await _create_profile(client, class_="merchant")
    row = await record_profile_settlement_outcome(
        db_session,
        profile_id=p["profile_id"],
        owner_identity_id="owner-1",
        identity_class="merchant",
        success=True,
        volume=20.0,
    )
    assert row is not None
    assert row.profile_id == p["profile_id"]
    assert row.successful_tasks == 1
    assert row.score > 100.0
