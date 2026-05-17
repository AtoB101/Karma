"""Strict per-task receipt chronology (attack MEDIUM: out-of-order timestamps)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from core.schemas import ExecutionReceipt, ToolStatus
from httptest import post_minimal_contract
from services.signing import signing_service


def _hex() -> str:
    return "c" * 64


def _signed_receipt(**kwargs) -> dict:
    now = datetime.now(timezone.utc)
    body = ExecutionReceipt(
        task_id=kwargs.get("task_id", "chrono-task"),
        agent_id=kwargs.get("agent_id", "worker-chrono"),
        step_index=kwargs["step_index"],
        tool_name="t",
        input_hash=_hex(),
        output_hash=_hex(),
        started_at=kwargs.get("started_at", now),
        ended_at=kwargs.get("ended_at", now + timedelta(seconds=1)),
        duration_ms=kwargs.get("duration_ms", 1000),
        status=ToolStatus.SUCCESS,
    )
    body.signature = signing_service.sign_receipt(body)
    return body.model_dump(mode="json")


@pytest.mark.asyncio
async def test_receipt_rejects_started_at_before_prior(client: AsyncClient):
    tid = "task-receipt-chrono-1"
    buyer, worker = "buyer-chrono-1", "worker-chrono-1"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 50.0})
    await post_minimal_contract(client, task_id=tid, client_agent_id=buyer, escrow_amount=10.0)
    await client.post(
        "/v1/settlement/create",
        json={"task_id": tid, "client_agent_id": buyer, "escrow_amount": 10.0, "currency": "USD"},
    )
    await client.post(f"/v1/settlement/{tid}/pending", json={})
    await client.post(f"/v1/settlement/{tid}/lock", json={"worker_agent_id": worker})
    await client.post(f"/v1/settlement/{tid}/start", json={})

    t0 = datetime.now(timezone.utc)
    r1 = await client.post(
        "/v1/receipts",
        json=_signed_receipt(
            task_id=tid,
            step_index=1,
            started_at=t0,
            ended_at=t0 + timedelta(seconds=2),
            duration_ms=2000,
        ),
    )
    assert r1.status_code == 201, r1.text

    r2 = await client.post(
        "/v1/receipts",
        json=_signed_receipt(
            task_id=tid,
            step_index=2,
            started_at=t0 - timedelta(seconds=10),
            ended_at=t0 + timedelta(seconds=3),
            duration_ms=13000,
        ),
    )
    assert r2.status_code == 409
    assert "started_at" in r2.json()["detail"].lower()
