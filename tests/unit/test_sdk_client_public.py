from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from sdk.client import KarmaClient
from core.schemas import ArbitrationVoteDecision, ProgressConfirmationStatus, ProgressReceipt, SubIdentityType


class _MockResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _MockHTTP:
    def __init__(self, routes: dict[tuple[str, str], dict]):
        self._routes = routes
        self.calls: list[tuple[str, str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str):
        self.calls.append(("GET", url, None))
        return _MockResponse(self._routes[("GET", url)])

    async def post(self, url: str, json: dict):
        self.calls.append(("POST", url, json))
        return _MockResponse(self._routes[("POST", url)])

    async def delete(self, url: str):
        self.calls.append(("DELETE", url, None))
        return _MockResponse(self._routes[("DELETE", url)])


@pytest.mark.asyncio
async def test_capacity_sdk_methods():
    base = "http://runtime"
    identity_id = "buyer-1"
    updated_at = datetime.utcnow().isoformat()
    routes = {
        ("GET", f"{base}/v1/capacity/{identity_id}"): {
            "identity_id": identity_id,
            "total_locked_usdc": 0,
            "total_bill_credits": 0,
            "available_credits": 0,
            "reserved_credits": 0,
            "in_progress_credits": 0,
            "confirmed_progress_credits": 0,
            "disputed_credits": 0,
            "pending_settlement_credits": 0,
            "burned_credits": 0,
            "released_credits": 0,
            "updated_at": updated_at,
        },
        ("POST", f"{base}/v1/capacity/{identity_id}/lock"): {
            "identity_id": identity_id,
            "total_locked_usdc": 100,
            "total_bill_credits": 100,
            "available_credits": 100,
            "reserved_credits": 0,
            "in_progress_credits": 0,
            "confirmed_progress_credits": 0,
            "disputed_credits": 0,
            "pending_settlement_credits": 0,
            "burned_credits": 0,
            "released_credits": 0,
            "updated_at": updated_at,
        },
        ("POST", f"{base}/v1/capacity/{identity_id}/release"): {
            "identity_id": identity_id,
            "total_locked_usdc": 80,
            "total_bill_credits": 80,
            "available_credits": 80,
            "reserved_credits": 0,
            "in_progress_credits": 0,
            "confirmed_progress_credits": 0,
            "disputed_credits": 0,
            "pending_settlement_credits": 0,
            "burned_credits": 0,
            "released_credits": 20,
            "updated_at": updated_at,
        },
    }
    mock_http = _MockHTTP(routes)
    client = KarmaClient(agent_id="a1", runtime_url=base)
    client._http = lambda: mock_http  # type: ignore[method-assign]

    cap0 = await client.get_capacity(identity_id)
    assert cap0.identity_id == identity_id
    cap1 = await client.lock_capacity(identity_id, 100)
    assert cap1.available_credits == 100
    cap2 = await client.release_capacity(identity_id, 20)
    assert cap2.released_credits == 20

    assert ("POST", f"{base}/v1/capacity/{identity_id}/lock", {"amount": 100}) in mock_http.calls
    assert ("POST", f"{base}/v1/capacity/{identity_id}/release", {"amount": 20}) in mock_http.calls


@pytest.mark.asyncio
async def test_voucher_sdk_methods():
    base = "http://runtime"
    voucher_id = "v-1"
    expiry = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    created = datetime.utcnow().isoformat()
    voucher_payload = {
        "voucher_id": voucher_id,
        "buyer_identity_id": "buyer-1",
        "seller_identity_id": "seller-1",
        "amount": 50,
        "currency": "USDC",
        "bill_credit_amount": 50,
        "task_type": "api-call",
        "task_description_hash": "a" * 64,
        "progress_rule_hash": "b" * 64,
        "evidence_requirement_hash": "c" * 64,
        "expiry_time": expiry,
        "nonce": "n-1",
        "buyer_signature": "sig",
        "status": "created",
        "buyer_sub_identity_id": None,
        "seller_sub_identity_id": None,
        "accepted_at": None,
        "created_at": created,
    }
    verify_payload = {
        "voucher_id": voucher_id,
        "is_authentic": True,
        "is_expired": False,
        "is_used": False,
        "amount_matches": True,
        "seller_matches": True,
        "has_sufficient_capacity": True,
        "can_start": True,
        "status": "created",
    }
    accepted_payload = dict(voucher_payload)
    accepted_payload["status"] = "accepted"
    accepted_payload["accepted_at"] = created

    routes = {
        ("POST", f"{base}/v1/vouchers"): voucher_payload,
        ("GET", f"{base}/v1/vouchers/{voucher_id}"): voucher_payload,
        ("POST", f"{base}/v1/vouchers/{voucher_id}/verify"): verify_payload,
        ("POST", f"{base}/v1/vouchers/{voucher_id}/accept"): accepted_payload,
    }
    mock_http = _MockHTTP(routes)
    client = KarmaClient(agent_id="a1", runtime_url=base)
    client._http = lambda: mock_http  # type: ignore[method-assign]

    created_voucher = await client.create_voucher(
        buyer_identity_id="buyer-1",
        seller_identity_id="seller-1",
        amount=50,
        bill_credit_amount=50,
        task_type="api-call",
        task_description_hash="a" * 64,
        progress_rule_hash="b" * 64,
        evidence_requirement_hash="c" * 64,
        expiry_time=expiry,
        nonce="n-1",
        buyer_signature="sig",
    )
    assert created_voucher.voucher_id == voucher_id

    fetched_voucher = await client.get_voucher(voucher_id)
    assert fetched_voucher.seller_identity_id == "seller-1"

    verification = await client.verify_voucher(voucher_id, "seller-1", expected_amount=50)
    assert verification.can_start is True

    accepted = await client.accept_voucher(voucher_id, "seller-1")
    assert accepted.status.value == "accepted"


@pytest.mark.asyncio
async def test_progress_and_regret_sdk_methods():
    base = "http://runtime"
    now = datetime.utcnow().isoformat()
    progress_id = "p-1"
    progress_payload = {
        "progress_receipt_id": progress_id,
        "task_id": "task-1",
        "seller_identity_id": "seller-1",
        "progress_percent": 20,
        "claimed_value_percent": 20,
        "evidence_hash": "a" * 64,
        "runtime_log_hash": "b" * 64,
        "timestamp": now,
        "seller_signature": "sig",
        "validation_method": "buyer_confirm",
        "confirmation_status": "pending",
        "confirmed_at": None,
    }
    confirmed_payload = dict(progress_payload)
    confirmed_payload["confirmation_status"] = "confirmed"
    confirmed_payload["confirmed_at"] = now
    settlement_payload = {
        "settlement_id": "s-1",
        "task_id": "task-1",
        "escrow_amount": 100,
        "currency": "USD",
        "status": "partial",
        "client_agent_id": "buyer-1",
        "worker_agent_id": "seller-1",
        "released_amount": 20,
        "refunded_amount": 80,
        "dispute_reason": "buyer regret",
        "arbitration_notes": "buyer regret with confirmed progress 20.00%",
        "created_at": now,
        "updated_at": now,
        "released_at": now,
        "settlement_mode": "offchain",
        "chain_id": None,
        "contract_address": None,
        "tx_hash": None,
        "evidence_bundle_hash": None,
        "onchain_status": None,
        "quote_id": None,
    }
    routes = {
        ("POST", f"{base}/v1/progress"): progress_payload,
        ("POST", f"{base}/v1/progress/{progress_id}/confirm"): confirmed_payload,
        ("GET", f"{base}/v1/progress/task/task-1"): [confirmed_payload],
        ("POST", f"{base}/v1/settlement/task-1/regret"): settlement_payload,
        ("POST", f"{base}/v1/settlement/task-1/partial"): settlement_payload,
    }
    mock_http = _MockHTTP(routes)
    client = KarmaClient(agent_id="a1", runtime_url=base)
    client._http = lambda: mock_http  # type: ignore[method-assign]

    submitted = await client.submit_progress(ProgressReceipt(**progress_payload))
    assert submitted.progress_receipt_id == progress_id
    confirmed = await client.confirm_progress(progress_id)
    assert confirmed.confirmation_status == ProgressConfirmationStatus.CONFIRMED
    listed = await client.list_progress("task-1")
    assert len(listed) == 1
    regret_state = await client.regret_task("task-1", buyer_identity_id="buyer-1", reason="buyer regret")
    assert regret_state.status.value == "partial"
    partial_state = await client.partial_settlement("task-1", 20, reason="manual partial")
    assert partial_state.released_amount == 20


@pytest.mark.asyncio
async def test_identity_and_dispute_sdk_methods():
    base = "http://runtime"
    now = datetime.utcnow().isoformat()
    identity_id = "buyer-identity-1"
    sub_id = "sub-1"
    profile_payload = {
        "identity_id": identity_id,
        "display_id": "Karma-ID-ABCD1234",
        "legal_identity_status": "unbound",
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    sub_payload = {
        "sub_identity_id": sub_id,
        "parent_identity_id": identity_id,
        "sub_identity_type": "buyer",
        "alias": "buyer-sub",
        "status": "active",
        "created_at": now,
        "deleted_at": None,
    }
    dispute_payload = {
        "settlement_id": "s-2",
        "task_id": "task-2",
        "escrow_amount": 100,
        "currency": "USD",
        "status": "disputed",
        "client_agent_id": identity_id,
        "worker_agent_id": "seller-1",
        "released_amount": None,
        "refunded_amount": None,
        "dispute_reason": "quality issue",
        "arbitration_notes": None,
        "created_at": now,
        "updated_at": now,
        "released_at": None,
        "settlement_mode": "offchain",
        "chain_id": None,
        "contract_address": None,
        "tx_hash": None,
        "evidence_bundle_hash": None,
        "onchain_status": None,
        "quote_id": None,
    }
    arbitrate_payload = dict(dispute_payload)
    arbitrate_payload["status"] = "buyer_wins"
    arbitrate_payload["released_amount"] = 0
    arbitrate_payload["refunded_amount"] = 100
    arbitrate_payload["arbitration_notes"] = "auto arbitration"
    routes = {
        ("POST", f"{base}/v1/identities/{identity_id}/profile/init"): profile_payload,
        ("GET", f"{base}/v1/identities/{identity_id}/profile"): profile_payload,
        ("POST", f"{base}/v1/identities/{identity_id}/rotate-display-id"): profile_payload,
        ("POST", f"{base}/v1/identities/{identity_id}/sub-identities"): sub_payload,
        ("GET", f"{base}/v1/identities/{identity_id}/sub-identities"): [sub_payload],
        ("DELETE", f"{base}/v1/identities/{identity_id}/sub-identities/{sub_id}"): sub_payload,
        ("POST", f"{base}/v1/settlement/task-2/dispute"): dispute_payload,
        ("POST", f"{base}/v1/settlement/task-2/auto-arbitrate"): arbitrate_payload,
    }
    mock_http = _MockHTTP(routes)
    client = KarmaClient(agent_id="a1", runtime_url=base)
    client._http = lambda: mock_http  # type: ignore[method-assign]

    profile = await client.init_identity_profile(identity_id)
    assert profile.identity_id == identity_id
    fetched = await client.get_identity_profile(identity_id)
    assert fetched.display_id.startswith("Karma-ID-")
    rotated = await client.rotate_display_id(identity_id)
    assert rotated.status == "active"

    sub = await client.create_sub_identity(identity_id, sub_identity_type=SubIdentityType.BUYER, alias="buyer-sub")
    assert sub.sub_identity_id == sub_id
    listed = await client.list_sub_identities(identity_id)
    assert len(listed) == 1
    deleted = await client.delete_sub_identity(identity_id, sub_id)
    assert deleted.alias == "buyer-sub"

    disputed = await client.open_dispute("task-2", reason="quality issue")
    assert disputed.status.value == "disputed"
    arbitrated = await client.auto_arbitrate("task-2")
    assert arbitrated.refunded_amount == 100


@pytest.mark.asyncio
async def test_arbitration_sdk_methods():
    base = "http://runtime"
    now = datetime.utcnow().isoformat()
    case_id = "case-1"
    task_id = "task-arb-1"
    pool_payload = {
        "arbitrator_identity_id": "arb-1",
        "stake_amount": 100.0,
        "status": "active",
        "joined_at": now,
        "updated_at": now,
    }
    case_payload = {
        "case_id": case_id,
        "task_id": task_id,
        "settlement_id": "s-arb-1",
        "opened_by": "buyer-1",
        "reason": "quality dispute",
        "status": "voting",
        "required_arbitrators": 2,
        "decided_outcome": None,
        "final_partial_percent": None,
        "created_at": now,
        "updated_at": now,
        "executed_at": None,
    }
    assignment_payload = {
        "assignment_id": "as-1",
        "case_id": case_id,
        "arbitrator_identity_id": "arb-1",
        "assigned_at": now,
        "status": "assigned",
    }
    material_payload = {
        "material_id": "mat-1",
        "case_id": case_id,
        "task_id": task_id,
        "submitted_by": "buyer-1",
        "bundle_id": "bundle-1",
        "progress_receipt_ids": [],
        "evidence_hashes": ["a" * 64],
        "package_hash": "b" * 64,
        "storage_uri": None,
        "format_version": "arbitration-material-v1",
        "submitted_at": now,
    }
    voted_case_payload = dict(case_payload)
    voted_case_payload["status"] = "decided"
    voted_case_payload["decided_outcome"] = "buyer_wins"
    settlement_payload = {
        "settlement_id": "s-arb-1",
        "task_id": task_id,
        "escrow_amount": 100,
        "currency": "USD",
        "status": "buyer_wins",
        "client_agent_id": "buyer-1",
        "worker_agent_id": "seller-1",
        "released_amount": 0,
        "refunded_amount": 100,
        "dispute_reason": "quality dispute",
        "arbitration_notes": "decentralized pool decision: buyer_wins",
        "created_at": now,
        "updated_at": now,
        "released_at": None,
        "settlement_mode": "offchain",
        "chain_id": None,
        "contract_address": None,
        "tx_hash": None,
        "evidence_bundle_hash": None,
        "onchain_status": None,
        "quote_id": None,
    }
    routes = {
        ("POST", f"{base}/v1/arbitration/pool/join"): pool_payload,
        ("GET", f"{base}/v1/arbitration/pool"): [pool_payload],
        ("POST", f"{base}/v1/arbitration/cases"): case_payload,
        ("POST", f"{base}/v1/arbitration/cases/{case_id}/assign-auto"): [assignment_payload],
        ("GET", f"{base}/v1/arbitration/cases/{case_id}/assignments"): [assignment_payload],
        ("POST", f"{base}/v1/arbitration/cases/{case_id}/materials"): material_payload,
        ("GET", f"{base}/v1/arbitration/cases/{case_id}/materials"): [material_payload],
        ("POST", f"{base}/v1/arbitration/cases/{case_id}/vote"): voted_case_payload,
        ("POST", f"{base}/v1/arbitration/cases/{case_id}/execute"): settlement_payload,
    }
    mock_http = _MockHTTP(routes)
    client = KarmaClient(agent_id="a1", runtime_url=base)
    client._http = lambda: mock_http  # type: ignore[method-assign]

    member = await client.join_arbitration_pool("arb-1", stake_amount=100.0)
    assert member.arbitrator_identity_id == "arb-1"
    pool = await client.list_arbitration_pool()
    assert len(pool) == 1

    case = await client.create_arbitration_case(task_id=task_id, opened_by="buyer-1", reason="quality dispute", required_arbitrators=2)
    assert case.case_id == case_id
    assignments = await client.assign_arbitrators(case_id, count=2)
    assert len(assignments) == 1
    listed_assignments = await client.list_arbitration_assignments(case_id)
    assert listed_assignments[0].arbitrator_identity_id == "arb-1"

    material = await client.submit_arbitration_material(
        case_id=case_id,
        submitted_by="buyer-1",
        bundle_id="bundle-1",
        evidence_hashes=["a" * 64],
    )
    assert material.case_id == case_id
    materials = await client.list_arbitration_materials(case_id)
    assert len(materials) == 1

    voted_case = await client.cast_arbitration_vote(
        case_id=case_id,
        arbitrator_identity_id="arb-1",
        decision=ArbitrationVoteDecision.BUYER_WINS,
    )
    assert voted_case.status.value == "decided"

    settled = await client.execute_arbitration_case(case_id)
    assert settled.status.value == "buyer_wins"

