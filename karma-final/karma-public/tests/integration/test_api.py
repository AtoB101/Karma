"""
Karma — Integration Tests
Full end-to-end API flow: register → contract → receipts → bundle → verify → settle
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Agent Registration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_agent(client: AsyncClient):
    resp = await client.post("/v1/agents", json={
        "name": "Test Worker",
        "role": "worker",
        "capabilities": ["captioning", "ocr"],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_id"]
    assert data["role"] == "worker"
    assert "captioning" in data["capabilities"]


@pytest.mark.asyncio
async def test_register_client_agent(client: AsyncClient):
    resp = await client.post("/v1/agents", json={
        "name": "Test Client",
        "role": "client",
    })
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_list_agents(client: AsyncClient):
    # Register two agents
    await client.post("/v1/agents", json={"name": "W1", "role": "worker"})
    await client.post("/v1/agents", json={"name": "W2", "role": "worker"})
    resp = await client.get("/v1/agents")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


@pytest.mark.asyncio
async def test_get_agent_not_found(client: AsyncClient):
    resp = await client.get("/v1/agents/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Task Contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_contract(client: AsyncClient):
    resp = await client.post("/v1/contracts", json={
        "client_agent_id": "client-integration-001",
        "title": "Integration Test Task",
        "description": "Caption 10 images",
        "expected_output_schema": {"type": "object"},
        "expected_step_count": 10,
        "escrow_amount": 50.0,
        "currency": "USD",
        "deadline_at": (datetime.utcnow() + timedelta(hours=2)).isoformat(),
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["task_id"]
    assert data["contract_hash"]   # should be set automatically
    assert data["escrow_amount"] == 50.0


@pytest.mark.asyncio
async def test_get_contract(client: AsyncClient):
    create = await client.post("/v1/contracts", json={
        "client_agent_id": "client-001",
        "title": "T",
        "description": "D",
        "expected_output_schema": {},
        "expected_step_count": 3,
        "escrow_amount": 10.0,
        "deadline_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
    })
    task_id = create.json()["task_id"]
    resp = await client.get(f"/v1/contracts/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["task_id"] == task_id


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_and_retrieve_receipt(client: AsyncClient):
    from datetime import datetime
    now = datetime.utcnow()
    receipt_data = {
        "task_id":    "task-int-001",
        "agent_id":   "worker-int-001",
        "step_index": 1,
        "tool_name":  "caption.generate",
        "input_hash": "a" * 64,
        "output_hash":"b" * 64,
        "started_at": now.isoformat(),
        "ended_at":   (now + timedelta(milliseconds=200)).isoformat(),
        "duration_ms":200,
        "status":     "success",
    }
    resp = await client.post("/v1/receipts", json=receipt_data)
    assert resp.status_code == 201
    receipt_id = resp.json()["receipt_id"]

    get_resp = await client.get(f"/v1/receipts/{receipt_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["tool_name"] == "caption.generate"


@pytest.mark.asyncio
async def test_list_receipts_by_task(client: AsyncClient):
    from datetime import datetime
    task_id = "task-list-receipts"
    now = datetime.utcnow()
    for i in range(1, 4):
        await client.post("/v1/receipts", json={
            "task_id":    task_id,
            "agent_id":   "worker-001",
            "step_index": i,
            "tool_name":  f"tool.{i}",
            "input_hash": "a" * 64,
            "output_hash":"b" * 64,
            "started_at": (now + timedelta(seconds=i)).isoformat(),
            "ended_at":   (now + timedelta(seconds=i, milliseconds=100)).isoformat(),
            "duration_ms":100,
            "status":     "success",
        })
    resp = await client.get(f"/v1/receipts/task/{task_id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 3
    assert [r["step_index"] for r in resp.json()] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Evidence Bundle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_bundle(client: AsyncClient):
    from datetime import datetime
    bundle_data = {
        "task_id":           "task-bundle-int-001",
        "task_contract_hash":"x" * 64,
        "receipt_ids":       ["r1", "r2", "r3"],
        "receipt_hashes":    ["h1", "h2", "h3"],
        "final_result_hash": "f" * 64,
        "total_steps":       3,
        "successful_steps":  3,
        "failed_steps":      0,
        "total_duration_ms": 450,
        "created_at":        datetime.utcnow().isoformat(),
    }
    resp = await client.post("/v1/bundles", json=bundle_data)
    assert resp.status_code == 201
    assert resp.json()["bundle_id"]


@pytest.mark.asyncio
async def test_get_bundle_by_task(client: AsyncClient):
    from datetime import datetime
    task_id = "task-bundle-get-001"
    await client.post("/v1/bundles", json={
        "task_id": task_id,
        "task_contract_hash": "x" * 64,
        "receipt_ids": [],
        "receipt_hashes": [],
        "final_result_hash": "f" * 64,
        "total_steps": 0,
        "successful_steps": 0,
        "failed_steps": 0,
        "total_duration_ms": 0,
        "created_at": datetime.utcnow().isoformat(),
    })
    resp = await client.get(f"/v1/bundles/task/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["task_id"] == task_id


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_settlement_lifecycle(client: AsyncClient):
    task_id = "task-settle-int-001"

    # Create
    resp = await client.post("/v1/settlement/create", json={
        "task_id":         task_id,
        "client_agent_id": "client-001",
        "escrow_amount":   100.0,
        "currency":        "USD",
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "created"

    # Lock
    resp = await client.post(f"/v1/settlement/{task_id}/lock", json={
        "worker_agent_id": "worker-001"
    })
    assert resp.json()["status"] == "locked"

    # Start
    resp = await client.post(f"/v1/settlement/{task_id}/start", json={})
    assert resp.json()["status"] == "running"

    # Submit
    resp = await client.post(f"/v1/settlement/{task_id}/submit", json={})
    assert resp.json()["status"] == "submitted"

    # Get state
    resp = await client.get(f"/v1/settlement/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["escrow_amount"] == 100.0


# ---------------------------------------------------------------------------
# Reputation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reputation_not_found(client: AsyncClient):
    resp = await client.get("/v1/reputation/nonexistent-agent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reputation_leaderboard(client: AsyncClient):
    resp = await client.get("/v1/reputation?limit=10")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
