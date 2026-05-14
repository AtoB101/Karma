"""Regression tests for public-repo mitigations from attack simulation (KSA-*)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import app
from core.schemas import ExecutionReceipt, ToolStatus
from db.session import get_db
from httptest import post_minimal_contract
from services.signing import signing_service


@pytest.mark.asyncio
async def test_post_security_policies_requires_authentication(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/security/policies",
                json={"config": {"failed_auth_threshold": 1}, "note": "anon", "rollout_percent": 100},
            )
            assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_submit_receipt_without_task_contract_returns_404(client):
    now = datetime.utcnow()
    r = ExecutionReceipt(
        task_id="no-such-contract-task-ksa011",
        agent_id="worker-x",
        step_index=1,
        tool_name="t",
        input_hash="a" * 64,
        output_hash="b" * 64,
        started_at=now,
        ended_at=now + timedelta(milliseconds=50),
        duration_ms=50,
        status=ToolStatus.SUCCESS,
    )
    r.signature = signing_service.sign_receipt(r)
    resp = await client.post("/v1/receipts", json=r.model_dump(mode="json"))
    assert resp.status_code == 404
    assert "task contract not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_settlement_lock_rejects_self_worker(client):
    tid = "task-self-worker-ksa028"
    buyer = "buyer-self-028"
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
    lock = await client.post(f"/v1/settlement/{tid}/lock", json={"worker_agent_id": buyer})
    assert lock.status_code == 409
    assert "cannot equal" in lock.json()["detail"].lower()
