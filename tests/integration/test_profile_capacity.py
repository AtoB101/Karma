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


async def _commit(db_session, *, bill_id: str, identity_id: str, amount: float) -> None:
    """v2 的「锁仓」：一笔钱包签过名的 commit。钱不进场，只给托管合约授权。"""
    from db.models.orm import AllowanceCommitModel
    from services.chain import allowance_escrow as escrow

    db_session.add(
        AllowanceCommitModel(
            bill_id=bill_id,
            identity_id=identity_id,
            wallet_address="0x" + "ab" * 20,
            amount_usdc=amount,
            commit_tx_hash="0x" + (bill_id.encode().hex().ljust(64, "0"))[:64],
            state=escrow.IDLE,
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_allocate_on_v2_wallet_commit_without_legacy_lock(client: AsyncClient, db_session):
    """v2 是非托管的：钱一直在用户自己钱包里，所以不会产生 v1 的 capacity 行。
    上限必须回落到钱包给出的有效 commit，否则子身份额度分配永远是 409。"""
    p = await _create_profile(client)
    await _commit(db_session, bill_id="bill-v2-alloc", identity_id="owner-1", amount=100.0)

    r = await client.put(
        "/v1/capacity/owner-1/allocations",
        json={"allocations": {p["profile_id"]: 60.0}},
        headers=OWNER,
    )
    assert r.status_code == 200, r.text
    assert r.json()["locked_usdc"] == 100.0
    assert r.json()["allocations"][0]["available_credits"] == 60.0

    r = await client.get("/v1/capacity/owner-1/allocations", headers=OWNER)
    assert r.status_code == 200
    assert r.json()["locked_usdc"] == 100.0

    # 超过钱包真正授权的额度 -> 409
    r = await client.put(
        "/v1/capacity/owner-1/allocations",
        json={"allocations": {p["profile_id"]: 140.0}},
        headers=OWNER,
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_v2_order_reserves_that_sub_identitys_quota(
    client: AsyncClient, db_session, monkeypatch
):
    """子身份额度不是装饰：agent 用它下单，额度被冻结；超了直接 409。"""
    from api.routes import escrow as escrow_route
    from services import profile_capacity

    buyer_profile = await _create_profile(client)
    await _commit(db_session, bill_id="bill-buyer", identity_id="owner-1", amount=100.0)
    await _commit(db_session, bill_id="bill-seller", identity_id="seller-1", amount=100.0)
    await client.put(
        "/v1/capacity/owner-1/allocations",
        json={"allocations": {buyer_profile["profile_id"]: 40.0}},
        headers=OWNER,
    )

    monkeypatch.setattr(escrow_route.escrow, "can_server_settle", lambda: True)

    def _fake_open(**kwargs):
        return {
            "binding_id": 4242,
            "scope_hash": "0x" + "11" * 32,
            "bind_tx_hash": "0x" + "22" * 32,
            "submit_tx_hash": "0x" + "33" * 32,
            "proof_hash": "0x" + "44" * 32,
            "pull_after": 1,
        }

    monkeypatch.setattr(escrow_route.escrow, "open_and_submit_order", _fake_open)

    def _order(amount: float) -> dict:
        return {
            "seller_bill_id": "bill-seller",
            "buyer_bill_id": "bill-buyer",
            "amount_usdc": amount,
            "task_id": "task-quota-1",
            "proof": "0x" + "55" * 32,
            "profile_id": buyer_profile["profile_id"],
        }

    r = await client.post("/v1/escrow/owner-1/orders", json=_order(30.0), headers=OWNER)
    assert r.status_code == 200, r.text
    assert r.json()["binding"]["buyer_profile_id"] == buyer_profile["profile_id"]

    row = await profile_capacity.get_profile_capacity(
        db_session, profile_id=buyer_profile["profile_id"]
    )
    assert row.in_progress_credits == 30.0
    assert row.available_credits == 10.0

    # 同一个子身份再下 20：可用只剩 10 -> 409，而且不该走到链上
    r = await client.post("/v1/escrow/owner-1/orders", json=_order(20.0), headers=OWNER)
    assert r.status_code == 409, r.text
    assert "profile credits" in r.json()["detail"]
