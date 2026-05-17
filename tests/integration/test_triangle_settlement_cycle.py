"""Integration: three-party payment ring A→B→C→A blocked on final lock (KSA2-034)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from httptest import post_minimal_contract


@pytest.mark.asyncio
async def test_lock_rejects_triangle_payment_cycle(client: AsyncClient):
    for agent in ("tri-a", "tri-b", "tri-c"):
        await client.post(f"/v1/capacity/{agent}/lock", json={"amount": 100.0})

    pairs = [("tri-a", "tri-b"), ("tri-b", "tri-c")]
    for i, (buyer, worker) in enumerate(pairs):
        tid = f"task-tri-{i}"
        await post_minimal_contract(client, task_id=tid, client_agent_id=buyer, escrow_amount=10.0)
        assert (
            await client.post(
                "/v1/settlement/create",
                json={"task_id": tid, "client_agent_id": buyer, "escrow_amount": 10.0, "currency": "USD"},
            )
        ).status_code == 201
        assert (await client.post(f"/v1/settlement/{tid}/pending", json={})).status_code == 200
        lk = await client.post(f"/v1/settlement/{tid}/lock", json={"worker_agent_id": worker})
        assert lk.status_code == 200, lk.text

    tid_close = "task-tri-close"
    await post_minimal_contract(client, task_id=tid_close, client_agent_id="tri-c", escrow_amount=10.0)
    assert (
        await client.post(
            "/v1/settlement/create",
            json={"task_id": tid_close, "client_agent_id": "tri-c", "escrow_amount": 10.0, "currency": "USD"},
        )
    ).status_code == 201
    assert (await client.post(f"/v1/settlement/{tid_close}/pending", json={})).status_code == 200

    lock = await client.post(
        f"/v1/settlement/{tid_close}/lock",
        json={"worker_agent_id": "tri-a"},
    )
    assert lock.status_code == 409
    assert "cycle" in lock.json()["detail"].lower()
