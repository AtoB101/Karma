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

    temporal = await client.get(f"/v1/responsibility/task/{task_id}/temporal-consistency")
    assert temporal.status_code == 200
    temporal_body = temporal.json()
    assert temporal_body["task_id"] == task_id
    assert temporal_body["total_edges"] == 3
    assert isinstance(temporal_body["issues"], list)

    score = await client.get("/v1/responsibility/identity/id-c/score?window_hours=24")
    assert score.status_code == 200
    score_body = score.json()
    assert score_body["identity_id"] == "id-c"
    assert score_body["signal_count"] >= 1
    assert score_body["weighted_points"] > 0
    assert score_body["risk_band"] in {"elevated", "high", "critical"}

    model = await client.get("/v1/responsibility/model/public-risk")
    assert model.status_code == 200
    model_body = model.json()
    assert model_body["model_version"] == "public-risk-v1"
    assert "cycle_authorization" in model_body["signal_type_weights"]

    features = await client.get("/v1/responsibility/identity/id-c/path-features?window_hours=24&max_hops=4")
    assert features.status_code == 200
    features_body = features.json()
    assert features_body["identity_id"] == "id-c"
    assert features_body["cycle_paths_detected"] >= 1

    scan = await client.post("/v1/responsibility/scan-runs", json={
        "identity_ids": ["id-a", "id-b", "id-c"],
        "scan_mode": "full",
        "window_hours": 24,
        "max_hops": 4,
        "min_score_threshold": 1.0,
    })
    assert scan.status_code == 201
    scan_body = scan.json()
    assert scan_body["run"]["status"] == "completed"
    assert scan_body["run"]["total_identities"] == 3
    scan_id = scan_body["run"]["scan_id"]

    fetched_scan = await client.get(f"/v1/responsibility/scan-runs/{scan_id}?findings_limit=50")
    assert fetched_scan.status_code == 200
    fetched_body = fetched_scan.json()
    assert fetched_body["run"]["scan_id"] == scan_id
    assert fetched_body["run"]["flagged_identities"] >= 1
    assert fetched_body["run"]["scan_mode"] == "full"
    assert fetched_body["run"]["execution_mode"] == "sync"

    async_scan = await client.post("/v1/responsibility/scan-runs", json={
        "identity_ids": ["id-a", "id-b"],
        "execution_mode": "async",
        "scan_mode": "full",
        "window_hours": 24,
        "max_hops": 4,
        "min_score_threshold": 1.0,
        "retry_max_attempts": 3,
        "retry_backoff_seconds": 30,
    })
    assert async_scan.status_code == 201
    async_scan_body = async_scan.json()
    async_scan_id = async_scan_body["run"]["scan_id"]
    assert async_scan_body["run"]["status"] == "pending"
    assert async_scan_body["run"]["execution_mode"] == "async"
    assert async_scan_body["run"]["current_attempt"] == 0

    async_scan_claimed = await client.post("/v1/responsibility/scan-runs/claim", json={
        "runner_identity_id": "runner-int-1",
        "lease_seconds": 300,
        "include_failed": True,
    })
    assert async_scan_claimed.status_code == 200
    async_claim_body = async_scan_claimed.json()
    assert async_claim_body["scan_id"] == async_scan_id
    assert async_claim_body["status"] == "claimed"
    assert async_claim_body["claimed_by"] == "runner-int-1"

    queue_stats = await client.get("/v1/responsibility/scan-runs/queue/stats")
    assert queue_stats.status_code == 200
    queue_stats_body = queue_stats.json()
    assert queue_stats_body["total_runs"] >= 2
    assert "claimed" in queue_stats_body["status_counts"]
    assert "dead_letter_count" in queue_stats_body

    ops_report = await client.get(
        "/v1/responsibility/scan-runs/ops/report"
        "?window_hours=24&recent_events_limit=50&top_failure_limit=10"
    )
    assert ops_report.status_code == 200
    ops_body = ops_report.json()
    assert ops_body["window_hours"] == 24
    assert "recent_events" in ops_body
    assert "top_failure_reasons" in ops_body
    assert "runner_activity" in ops_body
    assert "alerts" in ops_body

    runner_activity = await client.get("/v1/responsibility/scan-runs/ops/runners?window_hours=24&limit=20")
    assert runner_activity.status_code == 200
    assert isinstance(runner_activity.json(), list)

    ops_alerts = await client.get("/v1/responsibility/scan-runs/ops/alerts?window_hours=24&runner_limit=20")
    assert ops_alerts.status_code == 200
    assert isinstance(ops_alerts.json(), list)

    recover_stale = await client.post("/v1/responsibility/scan-runs/recover-stale", json={"limit": 50})
    assert recover_stale.status_code == 200
    recover_body = recover_stale.json()
    assert recover_body["limit"] == 50
    assert recover_body["recovered_count"] >= 0

    pull_execute = await client.post("/v1/responsibility/scan-runs/worker/pull-execute", json={
        "runner_identity_id": "runner-int-ops",
        "lease_seconds": 300,
        "include_failed": True,
        "force_execute": False,
    })
    assert pull_execute.status_code == 200
    pull_execute_body = pull_execute.json()
    assert pull_execute_body["outcome"] in {"idle", "completed", "failed"}

    maintenance_tick = await client.post("/v1/responsibility/scan-runs/maintenance/tick", json={
        "runner_identity_id": "runner-int-ops",
        "recover_limit": 50,
        "max_claim_execute": 2,
        "lease_seconds": 300,
        "include_failed": True,
    })
    assert maintenance_tick.status_code == 200
    maintenance_body = maintenance_tick.json()
    assert maintenance_body["runner_identity_id"] == "runner-int-ops"
    assert maintenance_body["max_claim_execute"] == 2

    async_scan_polled = await client.get(f"/v1/responsibility/scan-runs/{async_scan_id}?findings_limit=50")
    assert async_scan_polled.status_code == 200
    assert async_scan_polled.json()["run"]["status"] == "claimed"

    async_scan_heartbeated = await client.post(
        f"/v1/responsibility/scan-runs/{async_scan_id}/heartbeat",
        json={"runner_identity_id": "runner-int-1", "lease_seconds": 300},
    )
    assert async_scan_heartbeated.status_code == 200
    assert async_scan_heartbeated.json()["status"] == "claimed"

    async_scan_executed = await client.post(
        f"/v1/responsibility/scan-runs/{async_scan_id}/execute",
        json={"force": False, "runner_identity_id": "runner-int-1", "lease_seconds": 300},
    )
    assert async_scan_executed.status_code == 200
    async_scan_executed_body = async_scan_executed.json()
    assert async_scan_executed_body["run"]["status"] == "completed"
    assert async_scan_executed_body["run"]["current_attempt"] == 1
    async_scan_events = await client.get(f"/v1/responsibility/scan-runs/{async_scan_id}/events?limit=50")
    assert async_scan_events.status_code == 200
    async_scan_event_types = [item["event_type"] for item in async_scan_events.json()]
    assert "created" in async_scan_event_types
    assert "claimed" in async_scan_event_types
    assert "execution_started" in async_scan_event_types
    assert "execution_completed" in async_scan_event_types

    extra = await client.post("/v1/responsibility/edges", json={
        "source_identity_id": "id-c",
        "target_identity_id": "id-d",
        "edge_type": "manual_link",
        "task_id": task_id,
    })
    assert extra.status_code == 201

    incremental_scan = await client.post("/v1/responsibility/scan-runs", json={
        "scan_mode": "incremental",
        "base_scan_id": scan_id,
        "window_hours": 24,
        "max_hops": 4,
        "min_score_threshold": 1.0,
    })
    assert incremental_scan.status_code == 201
    incremental_body = incremental_scan.json()
    assert incremental_body["run"]["scan_mode"] == "incremental"
    assert incremental_body["run"]["base_scan_id"] == scan_id

    failing_async_scan = await client.post("/v1/responsibility/scan-runs", json={
        "execution_mode": "async",
        "scan_mode": "incremental",
        "base_scan_id": "missing-run",
        "window_hours": 24,
        "max_hops": 4,
        "min_score_threshold": 1.0,
        "retry_max_attempts": 2,
        "retry_backoff_seconds": 60,
    })
    assert failing_async_scan.status_code == 201
    failing_scan_id = failing_async_scan.json()["run"]["scan_id"]

    failed_execute = await client.post(
        f"/v1/responsibility/scan-runs/{failing_scan_id}/execute",
        json={"force": False},
    )
    assert failed_execute.status_code == 404

    failed_scan = await client.get(f"/v1/responsibility/scan-runs/{failing_scan_id}?findings_limit=50")
    assert failed_scan.status_code == 200
    failed_scan_body = failed_scan.json()
    assert failed_scan_body["run"]["status"] == "failed"
    assert failed_scan_body["run"]["last_error"] is not None
    assert failed_scan_body["run"]["next_retry_at"] is not None

    failed_retry = await client.post(f"/v1/responsibility/scan-runs/{failing_scan_id}/retry")
    assert failed_retry.status_code == 409

    exhausted_scan = await client.post("/v1/responsibility/scan-runs", json={
        "execution_mode": "async",
        "scan_mode": "incremental",
        "base_scan_id": "missing-run-exhausted",
        "window_hours": 24,
        "max_hops": 4,
        "min_score_threshold": 1.0,
        "retry_max_attempts": 1,
        "retry_backoff_seconds": 10,
    })
    assert exhausted_scan.status_code == 201
    exhausted_scan_id = exhausted_scan.json()["run"]["scan_id"]

    exhausted_execute = await client.post(
        f"/v1/responsibility/scan-runs/{exhausted_scan_id}/execute",
        json={"force": False},
    )
    assert exhausted_execute.status_code == 404

    dead_letter_sweep = await client.post(
        "/v1/responsibility/scan-runs/dead-letter/sweep",
        json={"limit": 100, "reason": "retry-exhausted"},
    )
    assert dead_letter_sweep.status_code == 200
    dead_letter_sweep_body = dead_letter_sweep.json()
    assert dead_letter_sweep_body["dead_lettered_count"] >= 1
    assert exhausted_scan_id in dead_letter_sweep_body["dead_lettered_scan_ids"]

    dead_letter_runs = await client.get("/v1/responsibility/scan-runs/dead-letter?limit=100")
    assert dead_letter_runs.status_code == 200
    dead_letter_ids = {item["scan_id"] for item in dead_letter_runs.json()}
    assert exhausted_scan_id in dead_letter_ids

    requeued_scan = await client.post(
        f"/v1/responsibility/scan-runs/{exhausted_scan_id}/requeue",
        json={"reason": "ops-requeue"},
    )
    assert requeued_scan.status_code == 200
    requeued_body = requeued_scan.json()
    assert requeued_body["status"] == "pending"
    assert requeued_body["current_attempt"] == 0

    requeue_events = await client.get(f"/v1/responsibility/scan-runs/{exhausted_scan_id}/events?limit=100")
    assert requeue_events.status_code == 200
    requeue_event_types = [item["event_type"] for item in requeue_events.json()]
    assert "dead_lettered" in requeue_event_types
    assert "requeued" in requeue_event_types

    exhausted_scan_batch = await client.post("/v1/responsibility/scan-runs", json={
        "execution_mode": "async",
        "scan_mode": "incremental",
        "base_scan_id": "missing-run-batch",
        "window_hours": 24,
        "max_hops": 4,
        "min_score_threshold": 1.0,
        "retry_max_attempts": 1,
        "retry_backoff_seconds": 10,
    })
    assert exhausted_scan_batch.status_code == 201
    exhausted_scan_batch_id = exhausted_scan_batch.json()["run"]["scan_id"]
    exhausted_batch_execute = await client.post(
        f"/v1/responsibility/scan-runs/{exhausted_scan_batch_id}/execute",
        json={"force": False},
    )
    assert exhausted_batch_execute.status_code == 404
    dead_letter_sweep_batch = await client.post(
        "/v1/responsibility/scan-runs/dead-letter/sweep",
        json={"limit": 100, "reason": "retry-exhausted-batch"},
    )
    assert dead_letter_sweep_batch.status_code == 200
    assert exhausted_scan_batch_id in dead_letter_sweep_batch.json()["dead_lettered_scan_ids"]

    requeue_batch = await client.post(
        "/v1/responsibility/scan-runs/dead-letter/requeue-batch",
        json={"limit": 100, "reason": "batch-redrive"},
    )
    assert requeue_batch.status_code == 200
    requeue_batch_body = requeue_batch.json()
    assert requeue_batch_body["requeued_count"] >= 1
    assert exhausted_scan_batch_id in requeue_batch_body["requeued_scan_ids"]

    purge_dead_letter = await client.post(
        "/v1/responsibility/scan-runs/dead-letter/purge",
        json={"limit": 100, "older_than_hours": 1},
    )
    assert purge_dead_letter.status_code == 200
    purge_dead_letter_body = purge_dead_letter.json()
    assert purge_dead_letter_body["older_than_hours"] == 1
    assert purge_dead_letter_body["purged_count"] >= 0

    cancellable_scan = await client.post("/v1/responsibility/scan-runs", json={
        "identity_ids": ["id-a"],
        "execution_mode": "async",
        "scan_mode": "full",
        "window_hours": 24,
        "max_hops": 4,
        "min_score_threshold": 1.0,
    })
    assert cancellable_scan.status_code == 201
    cancellable_scan_id = cancellable_scan.json()["run"]["scan_id"]

    cancel_resp = await client.post(
        f"/v1/responsibility/scan-runs/{cancellable_scan_id}/cancel",
        json={"runner_identity_id": "ops-int-1", "reason": "maintenance-window"},
    )
    assert cancel_resp.status_code == 200
    cancel_body = cancel_resp.json()
    assert cancel_body["status"] == "cancelled"
    assert cancel_body["cancel_reason"] == "maintenance-window"

    report_identity = await client.post("/v1/responsibility/reports/export", json={
        "identity_id": "id-c",
        "signer_identity_id": "risk-ops-001",
        "signature": "sig-placeholder",
        "window_hours": 24,
        "max_hops": 4,
        "top_signals_limit": 10,
    })
    assert report_identity.status_code == 200
    identity_report_body = report_identity.json()
    assert identity_report_body["target"] == "identity"
    assert identity_report_body["identity_id"] == "id-c"
    assert identity_report_body["content_hash"]
    assert identity_report_body["signature"]["status"] == "provided"
    assert identity_report_body["signature"]["signer_identity_id"] == "risk-ops-001"

    report_task = await client.post("/v1/responsibility/reports/export", json={
        "task_id": task_id,
        "window_hours": 24,
        "max_hops": 4,
        "top_signals_limit": 10,
    })
    assert report_task.status_code == 200
    task_report_body = report_task.json()
    assert task_report_body["target"] == "task"
    assert task_report_body["task_id"] == task_id
    assert task_report_body["temporal_consistency"]["task_id"] == task_id
    assert task_report_body["signature"]["status"] in {"unsigned", "provided"}


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
