"""Optional settlement linearity: lock requires pending first."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from config.settings import settings


@pytest.mark.asyncio
async def test_lock_from_draft_blocked_when_pending_required(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "settlement_lock_requires_pending", True)
    buyer, worker = "buyer-pend-lock-1", "worker-pend-lock-1"
    tid = "task-pend-lock-1"
    await client.post(
        "/v1/settlement/create",
        json={"task_id": tid, "client_agent_id": buyer, "escrow_amount": 10.0, "currency": "USD"},
    )
    r = await client.post(f"/v1/settlement/{tid}/lock", json={"worker_agent_id": worker})
    assert r.status_code == 409
    assert "pending" in r.json()["detail"].lower()

    ok = await client.post(f"/v1/settlement/{tid}/pending", json={})
    assert ok.status_code == 200
    r2 = await client.post(f"/v1/settlement/{tid}/lock", json={"worker_agent_id": worker})
    assert r2.status_code == 200

    monkeypatch.setattr(settings, "settlement_lock_requires_pending", False)
