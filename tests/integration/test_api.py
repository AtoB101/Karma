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


@pytest.mark.asyncio
async def test_settlement_invalid_transition_rejected(client: AsyncClient):
    task_id = "task-settle-invalid-001"
    await client.post("/v1/settlement/create", json={
        "task_id": task_id,
        "client_agent_id": "client-001",
        "escrow_amount": 10.0,
        "currency": "USD",
    })

    # created -> submitted is invalid
    resp = await client.post(f"/v1/settlement/{task_id}/submit", json={})
    assert resp.status_code == 409
    assert "invalid status transition" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_progress_receipt_and_buyer_regret_flow(client: AsyncClient):
    task_id = "task-progress-regret-001"
    buyer = "buyer-progress-001"
    seller = "seller-progress-001"

    # Capacity + reservation to simulate an authorized task.
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100})
    voucher = await client.post("/v1/vouchers", json={
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": 100,
        "currency": "USDC",
        "bill_credit_amount": 100,
        "task_type": "agent-task",
        "task_description_hash": "a" * 64,
        "progress_rule_hash": "b" * 64,
        "evidence_requirement_hash": "c" * 64,
        "expiry_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        "nonce": "nonce-progress-001",
        "buyer_signature": "sig-progress-001",
    })
    voucher_id = voucher.json()["voucher_id"]
    await client.post(f"/v1/vouchers/{voucher_id}/accept", json={"seller_identity_id": seller})

    # Settlement lifecycle to running.
    await client.post("/v1/settlement/create", json={
        "task_id": task_id,
        "client_agent_id": buyer,
        "escrow_amount": 100.0,
        "currency": "USD",
    })
    await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": seller})
    await client.post(f"/v1/settlement/{task_id}/start", json={})

    progress = await client.post("/v1/progress", json={
        "task_id": task_id,
        "seller_identity_id": seller,
        "progress_percent": 20,
        "claimed_value_percent": 20,
        "evidence_hash": "d" * 64,
        "runtime_log_hash": "e" * 64,
        "seller_signature": "sig-seller",
        "validation_method": "buyer_confirm",
    })
    assert progress.status_code == 201
    progress_id = progress.json()["progress_receipt_id"]

    confirm = await client.post(f"/v1/progress/{progress_id}/confirm", json={})
    assert confirm.status_code == 200
    assert confirm.json()["confirmation_status"] == "confirmed"

    regret = await client.post(f"/v1/settlement/{task_id}/regret", json={
        "buyer_identity_id": buyer,
        "reason": "buyer regret",
    })
    assert regret.status_code == 200
    assert regret.json()["status"] == "partial"
    assert regret.json()["released_amount"] == 20.0
    assert regret.json()["refunded_amount"] == 80.0

    cap = await client.get(f"/v1/capacity/{buyer}")
    assert cap.status_code == 200
    payload = cap.json()
    assert payload["reserved_credits"] == 0
    assert payload["burned_credits"] == 20.0
    assert payload["released_credits"] == 80.0


@pytest.mark.asyncio
async def test_manual_partial_settlement(client: AsyncClient):
    task_id = "task-manual-partial-001"
    await client.post("/v1/settlement/create", json={
        "task_id": task_id,
        "client_agent_id": "client-001",
        "escrow_amount": 100.0,
        "currency": "USD",
    })
    await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": "worker-001"})
    await client.post(f"/v1/settlement/{task_id}/start", json={})

    partial = await client.post(f"/v1/settlement/{task_id}/partial", json={
        "settled_value_percent": 40,
        "reason": "milestone-1",
    })
    assert partial.status_code == 200
    assert partial.json()["status"] == "partial"
    assert partial.json()["released_amount"] == 40.0
    assert partial.json()["refunded_amount"] == 60.0


# ---------------------------------------------------------------------------
# Dispute and auto-arbitration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_arbitration_rule_buyer_wins_without_confirmed_progress(client: AsyncClient):
    task_id = "task-auto-arbitrate-001"

    await client.post("/v1/settlement/create", json={
        "task_id": task_id,
        "client_agent_id": "buyer-001",
        "escrow_amount": 50.0,
        "currency": "USD",
    })
    await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": "seller-001"})
    await client.post(f"/v1/settlement/{task_id}/start", json={})
    await client.post(f"/v1/settlement/{task_id}/submit", json={})

    dispute = await client.post(f"/v1/settlement/{task_id}/dispute", json={"reason": "quality issue"})
    assert dispute.status_code == 200
    assert dispute.json()["status"] == "disputed"

    arbitrate = await client.post(f"/v1/settlement/{task_id}/auto-arbitrate", json={})
    assert arbitrate.status_code == 200
    assert arbitrate.json()["status"] == "buyer_wins"
    assert arbitrate.json()["released_amount"] == 0.0
    assert arbitrate.json()["refunded_amount"] == 50.0


# ---------------------------------------------------------------------------
# Identity profile and sub-identities
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sub_identity_limit_and_display_rotation(client: AsyncClient):
    identity_id = "identity-parent-001"

    init = await client.post(f"/v1/identities/{identity_id}/profile/init", json={})
    assert init.status_code == 200
    display_before = init.json()["display_id"]

    create_1 = await client.post(f"/v1/identities/{identity_id}/sub-identities", json={
        "sub_identity_type": "buyer",
        "alias": "buyer-sub",
    })
    assert create_1.status_code == 201

    create_2 = await client.post(f"/v1/identities/{identity_id}/sub-identities", json={
        "sub_identity_type": "agent",
        "alias": "agent-sub",
    })
    assert create_2.status_code == 201

    create_3 = await client.post(f"/v1/identities/{identity_id}/sub-identities", json={
        "sub_identity_type": "project",
        "alias": "project-sub",
    })
    assert create_3.status_code == 409

    rotate = await client.post(f"/v1/identities/{identity_id}/rotate-display-id", json={})
    assert rotate.status_code == 200
    display_after = rotate.json()["display_id"]
    assert display_after != display_before


@pytest.mark.asyncio
async def test_voucher_validates_sub_identity_parent_binding(client: AsyncClient):
    buyer = "identity-buyer-001"
    seller = "identity-seller-001"
    await client.post(f"/v1/identities/{buyer}/profile/init", json={})
    await client.post(f"/v1/identities/{seller}/profile/init", json={})
    buyer_sub = await client.post(f"/v1/identities/{buyer}/sub-identities", json={
        "sub_identity_type": "buyer",
        "alias": "buyer-sub-1",
    })
    seller_sub = await client.post(f"/v1/identities/{seller}/sub-identities", json={
        "sub_identity_type": "seller",
        "alias": "seller-sub-1",
    })
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100})

    valid = await client.post("/v1/vouchers", json={
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": 60,
        "currency": "USDC",
        "bill_credit_amount": 60,
        "task_type": "agent-task",
        "task_description_hash": "a" * 64,
        "progress_rule_hash": "b" * 64,
        "evidence_requirement_hash": "c" * 64,
        "expiry_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        "nonce": "nonce-sub-valid",
        "buyer_signature": "sig-sub-valid",
        "buyer_sub_identity_id": buyer_sub.json()["sub_identity_id"],
        "seller_sub_identity_id": seller_sub.json()["sub_identity_id"],
    })
    assert valid.status_code == 201

    invalid = await client.post("/v1/vouchers", json={
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": 10,
        "currency": "USDC",
        "bill_credit_amount": 10,
        "task_type": "agent-task",
        "task_description_hash": "d" * 64,
        "progress_rule_hash": "e" * 64,
        "evidence_requirement_hash": "f" * 64,
        "expiry_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        "nonce": "nonce-sub-invalid",
        "buyer_signature": "sig-sub-invalid",
        # buyer is trying to use seller's sub identity -> must fail
        "buyer_sub_identity_id": seller_sub.json()["sub_identity_id"],
    })
    assert invalid.status_code == 409


# ---------------------------------------------------------------------------
# Arbitration pool and decentralized case flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_arbitration_pool_case_material_vote_execute(client: AsyncClient):
    task_id = "task-arb-flow-001"
    buyer_id = "buyer-arb-001"

    await client.post("/v1/settlement/create", json={
        "task_id": task_id,
        "client_agent_id": buyer_id,
        "escrow_amount": 100.0,
        "currency": "USD",
    })
    await client.post(f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": "seller-arb-001"})
    await client.post(f"/v1/settlement/{task_id}/start", json={})
    await client.post(f"/v1/settlement/{task_id}/submit", json={})
    disputed = await client.post(f"/v1/settlement/{task_id}/dispute", json={"reason": "quality issue"})
    assert disputed.status_code == 200
    assert disputed.json()["status"] == "disputed"

    pool_1 = await client.post("/v1/arbitration/pool/join", json={
        "arbitrator_identity_id": "arb-001",
        "stake_amount": 10.0,
    })
    pool_2 = await client.post("/v1/arbitration/pool/join", json={
        "arbitrator_identity_id": "arb-002",
        "stake_amount": 8.0,
    })
    assert pool_1.status_code == 200
    assert pool_2.status_code == 200

    created_case = await client.post("/v1/arbitration/cases", json={
        "task_id": task_id,
        "opened_by": buyer_id,
        "reason": "quality issue",
        "required_arbitrators": 2,
    })
    assert created_case.status_code == 201
    case_id = created_case.json()["case_id"]
    assert created_case.json()["status"] in {"open", "voting"}

    assigned = await client.post(f"/v1/arbitration/cases/{case_id}/assign-auto", json={"count": 2})
    assert assigned.status_code == 200
    assert len(assigned.json()) == 2

    material = await client.post(f"/v1/arbitration/cases/{case_id}/materials", json={
        "submitted_by": buyer_id,
        "bundle_id": "bundle-arb-001",
        "evidence_hashes": ["AA" * 32, "aa" * 32, "BB" * 32],
    })
    assert material.status_code == 201
    # Normalized: lowercase + dedupe + sort
    assert material.json()["evidence_hashes"] == ["aa" * 32, "bb" * 32]

    vote_1 = await client.post(f"/v1/arbitration/cases/{case_id}/vote", json={
        "arbitrator_identity_id": "arb-001",
        "decision": "buyer_wins",
        "rationale": "hash mismatch",
    })
    assert vote_1.status_code == 200
    assert vote_1.json()["status"] in {"voting", "decided"}

    vote_2 = await client.post(f"/v1/arbitration/cases/{case_id}/vote", json={
        "arbitrator_identity_id": "arb-002",
        "decision": "buyer_wins",
        "rationale": "invalid format",
    })
    assert vote_2.status_code == 200
    assert vote_2.json()["status"] == "decided"
    assert vote_2.json()["decided_outcome"] == "buyer_wins"

    executed = await client.post(f"/v1/arbitration/cases/{case_id}/execute", json={})
    assert executed.status_code == 200
    assert executed.json()["status"] == "buyer_wins"
    assert executed.json()["refunded_amount"] == 100.0


# ---------------------------------------------------------------------------
# Capacity & Vouchers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capacity_lock_and_release(client: AsyncClient):
    identity = "buyer-cap-001"

    lock = await client.post(f"/v1/capacity/{identity}/lock", json={"amount": 120})
    assert lock.status_code == 200
    payload = lock.json()
    assert payload["total_locked_usdc"] == 120
    assert payload["available_credits"] == 120
    assert payload["total_bill_credits"] == 120

    release = await client.post(f"/v1/capacity/{identity}/release", json={"amount": 20})
    assert release.status_code == 200
    payload = release.json()
    assert payload["total_locked_usdc"] == 100
    assert payload["available_credits"] == 100
    assert payload["released_credits"] == 20


@pytest.mark.asyncio
async def test_voucher_accept_reserves_capacity(client: AsyncClient):
    buyer = "buyer-voucher-001"
    seller = "seller-voucher-001"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 200})

    create = await client.post("/v1/vouchers", json={
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": 150,
        "currency": "USDC",
        "bill_credit_amount": 150,
        "task_type": "api-call",
        "task_description_hash": "a" * 64,
        "progress_rule_hash": "b" * 64,
        "evidence_requirement_hash": "c" * 64,
        "expiry_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        "nonce": "nonce-001",
        "buyer_signature": "sig-001",
    })
    assert create.status_code == 201
    voucher_id = create.json()["voucher_id"]

    verify = await client.post(f"/v1/vouchers/{voucher_id}/verify", json={
        "seller_identity_id": seller,
        "expected_amount": 150,
    })
    assert verify.status_code == 200
    assert verify.json()["can_start"] is True

    accept = await client.post(f"/v1/vouchers/{voucher_id}/accept", json={
        "seller_identity_id": seller
    })
    assert accept.status_code == 200
    assert accept.json()["status"] == "accepted"

    cap = await client.get(f"/v1/capacity/{buyer}")
    assert cap.status_code == 200
    body = cap.json()
    assert body["available_credits"] == 50
    assert body["reserved_credits"] == 150

    second_accept = await client.post(f"/v1/vouchers/{voucher_id}/accept", json={
        "seller_identity_id": seller
    })
    assert second_accept.status_code == 409


@pytest.mark.asyncio
async def test_responsibility_graph_detects_mutual_exchange_from_voucher_accept(client: AsyncClient):
    buyer = "buyer-loop-001"
    seller = "seller-loop-001"
    await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100})

    create = await client.post("/v1/vouchers", json={
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": 80,
        "currency": "USDC",
        "bill_credit_amount": 80,
        "task_type": "delegation",
        "task_description_hash": "d" * 64,
        "progress_rule_hash": "e" * 64,
        "evidence_requirement_hash": "f" * 64,
        "expiry_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        "nonce": "nonce-loop-001",
        "buyer_signature": "sig-loop-001",
    })
    assert create.status_code == 201
    voucher_id = create.json()["voucher_id"]

    accepted = await client.post(f"/v1/vouchers/{voucher_id}/accept", json={"seller_identity_id": seller})
    assert accepted.status_code == 200

    reverse = await client.post("/v1/responsibility/edges", json={
        "source_identity_id": seller,
        "target_identity_id": buyer,
        "edge_type": "manual_link",
    })
    assert reverse.status_code == 201
    signal_types = {item["signal_type"] for item in reverse.json()["signals"]}
    assert "mutual_exchange" in signal_types


@pytest.mark.asyncio
async def test_responsibility_graph_cycle_detection_and_task_path_hash(client: AsyncClient):
    task_id = "task-path-cycle-001"
    edge_1 = await client.post("/v1/responsibility/edges", json={
        "source_identity_id": "id-a",
        "target_identity_id": "id-b",
        "edge_type": "task_delegation",
        "task_id": task_id,
    })
    edge_2 = await client.post("/v1/responsibility/edges", json={
        "source_identity_id": "id-b",
        "target_identity_id": "id-c",
        "edge_type": "task_delegation",
        "task_id": task_id,
    })
    edge_3 = await client.post("/v1/responsibility/edges", json={
        "source_identity_id": "id-c",
        "target_identity_id": "id-a",
        "edge_type": "task_delegation",
        "task_id": task_id,
    })
    assert edge_1.status_code == 201
    assert edge_2.status_code == 201
    assert edge_3.status_code == 201
    signal_types = {item["signal_type"] for item in edge_3.json()["signals"]}
    assert "cycle_authorization" in signal_types

    signals = await client.get("/v1/responsibility/identity/id-c/signals?limit=10")
    assert signals.status_code == 200
    assert any(item["signal_type"] == "cycle_authorization" for item in signals.json())

    summary = await client.get(f"/v1/responsibility/task/{task_id}/path-hash")
    assert summary.status_code == 200
    body = summary.json()
    assert len(body["edge_hashes"]) == 3
    assert body["path_hash"] is not None


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
