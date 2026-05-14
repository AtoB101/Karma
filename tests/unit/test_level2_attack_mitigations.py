"""Regression tests for Level 2 attack simulation (KSA2-*)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient

from httptest import post_minimal_contract


@pytest.mark.asyncio
async def test_partial_settlement_without_execution_receipt_returns_409(client: AsyncClient):
    tid = "task-l2-no-rcpt-partial"
    buyer = "buyer-l2-partial-norcpt"
    worker = "worker-l2-partial-norcpt"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 50.0})
    await post_minimal_contract(
        client,
        task_id=tid,
        client_agent_id=buyer,
        escrow_amount=10.0,
        expected_step_count=1,
    )
    c = await client.post(
        "/v1/settlement/create",
        json={"task_id": tid, "client_agent_id": buyer, "escrow_amount": 10.0, "currency": "USD"},
    )
    assert c.status_code == 201, c.text
    await client.post(f"/v1/settlement/{tid}/pending", json={})
    lk = await client.post(f"/v1/settlement/{tid}/lock", json={"worker_agent_id": worker})
    assert lk.status_code == 200, lk.text
    await client.post(f"/v1/settlement/{tid}/start", json={})
    await client.post(f"/v1/settlement/{tid}/submit", json={})

    partial = await client.post(
        f"/v1/settlement/{tid}/partial",
        json={"settled_value_percent": 50.0, "reason": "no receipts"},
    )
    assert partial.status_code == 409
    assert "execution receipt" in partial.json()["detail"].lower()


@pytest.mark.asyncio
async def test_contract_title_rejects_rlo_unicode(client: AsyncClient):
    buyer = "buyer-l2-rlo"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 30.0})
    deadline = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    r = await client.post(
        "/v1/contracts",
        json={
            "client_agent_id": buyer,
            "title": "safe\u202eprefix",
            "description": "d",
            "expected_output_schema": {},
            "expected_step_count": 1,
            "escrow_amount": 5.0,
            "currency": "USD",
            "deadline_at": deadline,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_contract_title_rejects_nul_byte(client: AsyncClient):
    buyer = "buyer-l2-nul"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 30.0})
    deadline = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    r = await client.post(
        "/v1/contracts",
        json={
            "client_agent_id": buyer,
            "title": "a\x00b",
            "description": "d",
            "expected_output_schema": {},
            "expected_step_count": 1,
            "escrow_amount": 5.0,
            "currency": "USD",
            "deadline_at": deadline,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_lock_rejects_five_party_buyer_worker_cycle(client: AsyncClient):
    agents = ["l2cyc-a", "l2cyc-b", "l2cyc-c", "l2cyc-d", "l2cyc-e"]
    for a in agents:
        await client.post(f"/v1/capacity/{a}/lock", json={"amount": 200.0})

    chain = [
        ("l2cyc-a", "l2cyc-b"),
        ("l2cyc-b", "l2cyc-c"),
        ("l2cyc-c", "l2cyc-d"),
        ("l2cyc-d", "l2cyc-e"),
    ]
    for i, (buyer, worker) in enumerate(chain):
        tid = f"task-l2-cyc-{i}"
        await post_minimal_contract(
            client,
            task_id=tid,
            client_agent_id=buyer,
            escrow_amount=10.0,
            expected_step_count=1,
        )
        cr = await client.post(
            "/v1/settlement/create",
            json={"task_id": tid, "client_agent_id": buyer, "escrow_amount": 10.0, "currency": "USD"},
        )
        assert cr.status_code == 201, cr.text
        assert (await client.post(f"/v1/settlement/{tid}/pending", json={})).status_code == 200
        lk = await client.post(f"/v1/settlement/{tid}/lock", json={"worker_agent_id": worker})
        assert lk.status_code == 200, lk.text

    tid_last = "task-l2-cyc-4"
    await post_minimal_contract(
        client,
        task_id=tid_last,
        client_agent_id="l2cyc-e",
        escrow_amount=10.0,
        expected_step_count=1,
    )
    assert (
        await client.post(
            "/v1/settlement/create",
            json={
                "task_id": tid_last,
                "client_agent_id": "l2cyc-e",
                "escrow_amount": 10.0,
                "currency": "USD",
            },
        )
    ).status_code == 201
    assert (await client.post(f"/v1/settlement/{tid_last}/pending", json={})).status_code == 200

    lock = await client.post(
        f"/v1/settlement/{tid_last}/lock",
        json={"worker_agent_id": "l2cyc-a"},
    )
    assert lock.status_code == 409
    assert "cycle" in lock.json()["detail"].lower()
