"""P1 integration guards — partial settlement vs confirmed progress, buyer regret identity, timeout-confirm."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_partial_settlement_rejects_above_confirmed_claimed(client: AsyncClient):
    task_id = "task-p1-partial-cap"
    buyer = "buyer-p1-partial-cap"
    seller = "seller-p1-partial-cap"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100})
    v = await client.post(
        "/v1/vouchers",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "amount": 100,
            "currency": "USDC",
            "bill_credit_amount": 100,
            "task_type": "agent.partial",
            "task_description_hash": "a" * 64,
            "progress_rule_hash": "b" * 64,
            "evidence_requirement_hash": "c" * 64,
            "expiry_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "nonce": "nonce-p1-partial-cap",
            "buyer_signature": "sig-p1-partial-cap",
        },
    )
    vid = v.json()["voucher_id"]
    await client.post(f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller})
    await client.post(
        "/v1/settlement/create",
        json={"task_id": task_id, "client_agent_id": buyer, "escrow_amount": 100.0, "currency": "USD"},
    )
    await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": seller})
    await client.post(f"/v1/settlement/{task_id}/start", json={})

    pr = await client.post(
        "/v1/progress",
        json={
            "task_id": task_id,
            "seller_identity_id": seller,
            "progress_percent": 25,
            "claimed_value_percent": 25,
            "evidence_hash": "d" * 64,
            "runtime_log_hash": "e" * 64,
            "seller_signature": "sig-seller-pc",
            "validation_method": "buyer_confirm",
        },
    )
    assert pr.status_code == 201
    pid = pr.json()["progress_receipt_id"]
    await client.post(f"/v1/progress/{pid}/confirm", json={})

    bad = await client.post(f"/v1/settlement/{task_id}/partial", json={"settled_value_percent": 60, "reason": "too much"})
    assert bad.status_code == 400
    assert "exceeds" in bad.json()["detail"].lower()

    ok = await client.post(f"/v1/settlement/{task_id}/partial", json={"settled_value_percent": 25, "reason": "at ceiling"})
    assert ok.status_code == 200
    assert ok.json()["released_amount"] == 25.0


@pytest.mark.asyncio
async def test_regret_rejects_mismatched_buyer_identity(client: AsyncClient):
    task_id = "task-p1-regret-buyer"
    buyer = "buyer-p1-regret"
    seller = "seller-p1-regret"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 50})
    v = await client.post(
        "/v1/vouchers",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "amount": 50,
            "currency": "USDC",
            "bill_credit_amount": 50,
            "task_type": "agent.regret",
            "task_description_hash": "a" * 64,
            "progress_rule_hash": "b" * 64,
            "evidence_requirement_hash": "c" * 64,
            "expiry_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "nonce": "nonce-p1-regret-buyer",
            "buyer_signature": "sig-p1-regret-buyer",
        },
    )
    await client.post(f"/v1/vouchers/{v.json()['voucher_id']}/accept", json={"seller_identity_id": seller})
    await client.post(
        "/v1/settlement/create",
        json={"task_id": task_id, "client_agent_id": buyer, "escrow_amount": 50.0, "currency": "USD"},
    )
    await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": seller})
    await client.post(f"/v1/settlement/{task_id}/start", json={})

    r = await client.post(f"/v1/settlement/{task_id}/regret", json={"buyer_identity_id": "someone-else", "reason": "x"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_progress_timeout_confirm_stale_pending(client: AsyncClient):
    task_id = "task-p1-timeout-confirm"
    buyer = "buyer-p1-tc"
    seller = "seller-p1-tc"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 40})
    v = await client.post(
        "/v1/vouchers",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "amount": 40,
            "currency": "USDC",
            "bill_credit_amount": 40,
            "task_type": "agent.tc",
            "task_description_hash": "a" * 64,
            "progress_rule_hash": "b" * 64,
            "evidence_requirement_hash": "c" * 64,
            "expiry_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "nonce": "nonce-p1-tc",
            "buyer_signature": "sig-p1-tc",
        },
    )
    await client.post(f"/v1/vouchers/{v.json()['voucher_id']}/accept", json={"seller_identity_id": seller})
    await client.post(
        "/v1/settlement/create",
        json={"task_id": task_id, "client_agent_id": buyer, "escrow_amount": 40.0, "currency": "USD"},
    )
    await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": seller})
    await client.post(f"/v1/settlement/{task_id}/start", json={})

    old_ts = (datetime.utcnow() - timedelta(hours=100)).isoformat()
    pr = await client.post(
        "/v1/progress",
        json={
            "task_id": task_id,
            "seller_identity_id": seller,
            "progress_percent": 10,
            "claimed_value_percent": 10,
            "evidence_hash": "1" * 64,
            "runtime_log_hash": "2" * 64,
            "seller_signature": "sig-tc",
            "validation_method": "timeout",
            "timestamp": old_ts,
        },
    )
    assert pr.status_code == 201

    tc = await client.post(f"/v1/progress/task/{task_id}/timeout-confirm?max_pending_hours=48")
    assert tc.status_code == 200
    body = tc.json()
    assert len(body) == 1
    assert body[0]["confirmation_status"] == "confirmed"
