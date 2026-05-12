from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from sdk.client import KarmaClient
from core.schemas import (
    ArbitrationVoteDecision,
    ProgressConfirmationStatus,
    ProgressReceipt,
    ResponsibilityEdgeType,
    ResponsibilityScanExecutionMode,
    ResponsibilityScanMode,
    SubIdentityType,
)


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


@pytest.mark.asyncio
async def test_responsibility_sdk_methods():
    base = "http://runtime"
    now = datetime.utcnow().isoformat()
    task_id = "task-resp-1"
    ingest_payload = {
        "edge": {
            "edge_id": "edge-1",
            "edge_hash": "a" * 64,
            "source_identity_id": "id-a",
            "target_identity_id": "id-b",
            "edge_type": "task_delegation",
            "task_id": task_id,
            "voucher_id": None,
            "metadata": {},
            "created_at": now,
        },
        "signals": [
            {
                "signal_id": "sig-1",
                "signal_type": "mutual_exchange",
                "severity": "medium",
                "identity_id": "id-a",
                "edge_hash": "a" * 64,
                "related_edge_hashes": ["a" * 64, "b" * 64],
                "task_id": task_id,
                "detail": "reverse edge detected",
                "created_at": now,
            }
        ],
    }
    routes = {
        ("POST", f"{base}/v1/responsibility/edges"): ingest_payload,
        ("GET", f"{base}/v1/responsibility/identity/id-a/signals?limit=10"): ingest_payload["signals"],
        ("GET", f"{base}/v1/responsibility/task/{task_id}/path-hash"): {
            "task_id": task_id,
            "edge_hashes": ["a" * 64, "b" * 64],
            "path_hash": "c" * 64,
        },
        ("GET", f"{base}/v1/responsibility/task/{task_id}/temporal-consistency"): {
            "task_id": task_id,
            "total_edges": 2,
            "is_consistent": False,
            "issues": [
                {
                    "issue_type": "missing_anchor_edge",
                    "severity": "medium",
                    "detail": "task has responsibility edges but no voucher_accept anchor edge",
                    "edge_hashes": ["a" * 64],
                }
            ],
            "analyzed_at": now,
        },
        ("GET", f"{base}/v1/responsibility/identity/id-a/path-features?window_hours=48&max_hops=5"): {
            "identity_id": "id-a",
            "window_hours": 48,
            "max_hops": 5,
            "traversed_edge_count": 4,
            "reachable_identity_count": 3,
            "cycle_paths_detected": 1,
            "path_hashes_sample": ["d" * 64],
            "computed_at": now,
        },
        ("GET", f"{base}/v1/responsibility/identity/id-a/score?window_hours=48"): {
            "identity_id": "id-a",
            "window_hours": 48,
            "model_version": "public-risk-v1",
            "weighted_points": 12.4,
            "normalized_score": 12.4,
            "signal_count": 2,
            "signal_type_counts": {"mutual_exchange": 1, "cycle_authorization": 1},
            "severity_counts": {"medium": 1, "high": 1},
            "risk_band": "elevated",
            "computed_at": now,
        },
        ("GET", f"{base}/v1/responsibility/model/public-risk"): {
            "model_version": "public-risk-v1",
            "time_window_rule": "include signals in now-window_hours to now",
            "severity_weights": {"info": 1.0, "medium": 2.5, "high": 4.0},
            "signal_type_weights": {"direct_loop": 3.0, "mutual_exchange": 2.0, "cycle_authorization": 3.5},
            "recency_floor": 0.2,
            "public_band_reference": {"low_min": 0.0, "elevated_min": 8.0, "high_min": 20.0, "critical_min": 35.0},
        },
        ("POST", f"{base}/v1/responsibility/scan-runs"): {
            "run": {
                "scan_id": "scan-1",
                "status": "completed",
                "execution_mode": "async",
                "scan_mode": "incremental",
                "base_scan_id": "scan-0",
                "incremental_since_at": now,
                "requested_identity_ids": ["id-a"],
                "window_hours": 48,
                "max_hops": 5,
                "min_score_threshold": 8.0,
                "retry_max_attempts": 3,
                "retry_backoff_seconds": 30,
                "current_attempt": 1,
                "started_at": now,
                "next_retry_at": None,
                "last_error": None,
                "total_identities": 2,
                "flagged_identities": 1,
                "created_at": now,
                "completed_at": now,
            },
            "findings": [
                {
                    "finding_id": "finding-1",
                    "scan_id": "scan-1",
                    "identity_id": "id-a",
                    "normalized_score": 12.4,
                    "risk_band": "elevated",
                    "signal_count": 2,
                    "cycle_paths_detected": 1,
                    "detail": "window_score=12.40, signals=2, cycles=1",
                    "created_at": now,
                }
            ],
        },
        ("GET", f"{base}/v1/responsibility/scan-runs/scan-1?findings_limit=20"): {
            "run": {
                "scan_id": "scan-1",
                "status": "completed",
                "execution_mode": "async",
                "scan_mode": "incremental",
                "base_scan_id": "scan-0",
                "incremental_since_at": now,
                "requested_identity_ids": ["id-a"],
                "window_hours": 48,
                "max_hops": 5,
                "min_score_threshold": 8.0,
                "retry_max_attempts": 3,
                "retry_backoff_seconds": 30,
                "current_attempt": 1,
                "started_at": now,
                "next_retry_at": None,
                "last_error": None,
                "total_identities": 2,
                "flagged_identities": 1,
                "created_at": now,
                "completed_at": now,
            },
            "findings": [
                {
                    "finding_id": "finding-1",
                    "scan_id": "scan-1",
                    "identity_id": "id-a",
                    "normalized_score": 12.4,
                    "risk_band": "elevated",
                    "signal_count": 2,
                    "cycle_paths_detected": 1,
                    "detail": "window_score=12.40, signals=2, cycles=1",
                    "created_at": now,
                }
            ],
        },
        ("GET", f"{base}/v1/responsibility/scan-runs/scan-1/events?limit=20"): [
            {
                "event_id": "evt-1",
                "scan_id": "scan-1",
                "event_type": "created",
                "detail": "scan run created",
                "metadata": {"execution_mode": "async"},
                "created_at": now,
            },
            {
                "event_id": "evt-2",
                "scan_id": "scan-1",
                "event_type": "execution_completed",
                "detail": "scan run execution completed",
                "metadata": {"attempt": 1},
                "created_at": now,
            },
        ],
        ("POST", f"{base}/v1/responsibility/scan-runs/claim"): {
            "scan_id": "scan-1",
            "status": "claimed",
            "execution_mode": "async",
            "scan_mode": "incremental",
            "base_scan_id": "scan-0",
            "incremental_since_at": now,
            "requested_identity_ids": ["id-a"],
            "window_hours": 48,
            "max_hops": 5,
            "min_score_threshold": 8.0,
            "retry_max_attempts": 3,
            "retry_backoff_seconds": 30,
            "current_attempt": 0,
            "claimed_by": "runner-1",
            "claimed_at": now,
            "lease_expires_at": now,
            "last_heartbeat_at": now,
            "started_at": None,
            "next_retry_at": None,
            "last_error": None,
            "cancelled_at": None,
            "cancel_reason": None,
            "total_identities": 0,
            "flagged_identities": 0,
            "created_at": now,
            "completed_at": None,
        },
        ("GET", f"{base}/v1/responsibility/scan-runs/queue/stats"): {
            "total_runs": 5,
            "status_counts": {"pending": 1, "claimed": 1, "running": 1, "failed": 1, "completed": 1, "dead_letter": 1},
            "claimable_pending": 1,
            "claimable_failed": 1,
            "dead_letter_count": 1,
            "stale_claimed": 0,
            "stale_running": 0,
            "generated_at": now,
        },
        ("GET", f"{base}/v1/responsibility/scan-runs/ops/report?window_hours=24&recent_events_limit=50&top_failure_limit=10&runner_limit=20"): {
            "window_hours": 24,
            "total_runs": 5,
            "status_counts": {"pending": 1, "claimed": 1, "running": 1, "failed": 1, "completed": 1, "dead_letter": 1},
            "claimable_pending": 1,
            "claimable_failed": 1,
            "dead_letter_count": 1,
            "stale_claimed": 0,
            "stale_running": 0,
            "top_failure_reasons": [
                {"reason": "base scan run not found", "count": 2, "last_seen_at": now}
            ],
            "recent_events": [
                {
                    "event_id": "evt-ops-1",
                    "scan_id": "scan-1",
                    "event_type": "execution_failed",
                    "detail": "scan run execution failed",
                    "metadata": {"attempt": 1},
                    "created_at": now,
                }
            ],
            "runner_activity": [
                {
                    "runner_identity_id": "runner-1",
                    "claimed_count": 1,
                    "heartbeat_count": 1,
                    "execution_started_count": 1,
                    "execution_completed_count": 1,
                    "execution_failed_count": 0,
                    "last_event_at": now,
                }
            ],
            "alerts": [
                {
                    "alert_id": "alert-ops-1",
                    "severity": "high",
                    "alert_type": "queue_dead_letter_pressure",
                    "message": "dead-letter queue pressure: 1",
                    "metadata": {"dead_letter_count": 1, "threshold": 1},
                    "generated_at": now,
                }
            ],
            "generated_at": now,
        },
        ("GET", f"{base}/v1/responsibility/scan-runs/ops/runners?window_hours=24&limit=20"): [
            {
                "runner_identity_id": "runner-1",
                "claimed_count": 1,
                "heartbeat_count": 1,
                "execution_started_count": 1,
                "execution_completed_count": 1,
                "execution_failed_count": 0,
                "last_event_at": now,
            }
        ],
        ("GET", f"{base}/v1/responsibility/scan-runs/ops/alerts?window_hours=24&runner_limit=20&dead_letter_threshold=5&stale_threshold=3&failed_ratio_threshold=0.25&runner_failure_min_started=3&runner_failure_ratio_threshold=0.5"): [
            {
                "alert_id": "alert-ops-1",
                "severity": "high",
                "alert_type": "queue_dead_letter_pressure",
                "message": "dead-letter queue pressure: 1",
                "metadata": {"dead_letter_count": 1, "threshold": 1},
                "generated_at": now,
            }
        ],
        ("POST", f"{base}/v1/responsibility/scan-runs/recover-stale"): {
            "limit": 100,
            "scanned_count": 1,
            "recovered_count": 1,
            "recovered_scan_ids": ["scan-1"],
            "generated_at": now,
        },
        ("GET", f"{base}/v1/responsibility/scan-runs/dead-letter?limit=20"): [
            {
                "scan_id": "scan-dlq-1",
                "status": "dead_letter",
                "execution_mode": "async",
                "scan_mode": "incremental",
                "base_scan_id": "scan-0",
                "incremental_since_at": now,
                "requested_identity_ids": ["id-z"],
                "window_hours": 48,
                "max_hops": 5,
                "min_score_threshold": 8.0,
                "retry_max_attempts": 1,
                "retry_backoff_seconds": 30,
                "current_attempt": 1,
                "claimed_by": None,
                "claimed_at": None,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "started_at": now,
                "next_retry_at": None,
                "last_error": "base scan run not found",
                "cancelled_at": None,
                "cancel_reason": None,
                "dead_lettered_at": now,
                "dead_letter_reason": "retry exhausted",
                "total_identities": 0,
                "flagged_identities": 0,
                "created_at": now,
                "completed_at": None,
            }
        ],
        ("POST", f"{base}/v1/responsibility/scan-runs/dead-letter/sweep"): {
            "limit": 100,
            "scanned_count": 1,
            "dead_lettered_count": 1,
            "dead_lettered_scan_ids": ["scan-dlq-1"],
            "generated_at": now,
        },
        ("POST", f"{base}/v1/responsibility/scan-runs/dead-letter/requeue-batch"): {
            "limit": 100,
            "scanned_count": 1,
            "requeued_count": 1,
            "requeued_scan_ids": ["scan-dlq-1"],
            "generated_at": now,
        },
        ("POST", f"{base}/v1/responsibility/scan-runs/dead-letter/purge"): {
            "limit": 100,
            "older_than_hours": 72,
            "scanned_count": 1,
            "purged_count": 1,
            "purged_scan_ids": ["scan-dlq-0"],
            "generated_at": now,
        },
        ("POST", f"{base}/v1/responsibility/scan-runs/worker/pull-execute"): {
            "runner_identity_id": "runner-1",
            "outcome": "completed",
            "claimed_scan_id": "scan-1",
            "run": {
                "scan_id": "scan-1",
                "status": "completed",
                "execution_mode": "async",
                "scan_mode": "incremental",
                "base_scan_id": "scan-0",
                "incremental_since_at": now,
                "requested_identity_ids": ["id-a"],
                "window_hours": 48,
                "max_hops": 5,
                "min_score_threshold": 8.0,
                "retry_max_attempts": 3,
                "retry_backoff_seconds": 30,
                "current_attempt": 1,
                "claimed_by": None,
                "claimed_at": None,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "started_at": now,
                "next_retry_at": None,
                "last_error": None,
                "cancelled_at": None,
                "cancel_reason": None,
                "total_identities": 2,
                "flagged_identities": 1,
                "created_at": now,
                "completed_at": now,
            },
            "message": "scan run executed",
            "generated_at": now,
        },
        ("POST", f"{base}/v1/responsibility/scan-runs/maintenance/tick"): {
            "runner_identity_id": "runner-ops",
            "recover_limit": 100,
            "max_claim_execute": 5,
            "recovered_count": 1,
            "recovered_scan_ids": ["scan-0"],
            "claimed_count": 1,
            "executed_count": 1,
            "failed_count": 0,
            "executed_scan_ids": ["scan-1"],
            "failed_scan_ids": [],
            "generated_at": now,
        },
        ("POST", f"{base}/v1/responsibility/scan-runs/scan-1/execute"): {
            "run": {
                "scan_id": "scan-1",
                "status": "completed",
                "execution_mode": "async",
                "scan_mode": "incremental",
                "base_scan_id": "scan-0",
                "incremental_since_at": now,
                "requested_identity_ids": ["id-a"],
                "window_hours": 48,
                "max_hops": 5,
                "min_score_threshold": 8.0,
                "retry_max_attempts": 3,
                "retry_backoff_seconds": 30,
                "current_attempt": 1,
                "claimed_by": None,
                "claimed_at": None,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "started_at": now,
                "next_retry_at": None,
                "last_error": None,
                "cancelled_at": None,
                "cancel_reason": None,
                "total_identities": 2,
                "flagged_identities": 1,
                "created_at": now,
                "completed_at": now,
            },
            "findings": [],
        },
        ("POST", f"{base}/v1/responsibility/scan-runs/scan-1/heartbeat"): {
            "scan_id": "scan-1",
            "status": "claimed",
            "execution_mode": "async",
            "scan_mode": "incremental",
            "base_scan_id": "scan-0",
            "incremental_since_at": now,
            "requested_identity_ids": ["id-a"],
            "window_hours": 48,
            "max_hops": 5,
            "min_score_threshold": 8.0,
            "retry_max_attempts": 3,
            "retry_backoff_seconds": 30,
            "current_attempt": 0,
            "claimed_by": "runner-1",
            "claimed_at": now,
            "lease_expires_at": now,
            "last_heartbeat_at": now,
            "started_at": None,
            "next_retry_at": None,
            "last_error": None,
            "cancelled_at": None,
            "cancel_reason": None,
            "total_identities": 0,
            "flagged_identities": 0,
            "created_at": now,
            "completed_at": None,
        },
        ("POST", f"{base}/v1/responsibility/scan-runs/scan-1/retry"): {
            "run": {
                "scan_id": "scan-1",
                "status": "completed",
                "execution_mode": "async",
                "scan_mode": "incremental",
                "base_scan_id": "scan-0",
                "incremental_since_at": now,
                "requested_identity_ids": ["id-a"],
                "window_hours": 48,
                "max_hops": 5,
                "min_score_threshold": 8.0,
                "retry_max_attempts": 3,
                "retry_backoff_seconds": 30,
                "current_attempt": 2,
                "claimed_by": None,
                "claimed_at": None,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "started_at": now,
                "next_retry_at": None,
                "last_error": None,
                "cancelled_at": None,
                "cancel_reason": None,
                "total_identities": 2,
                "flagged_identities": 1,
                "created_at": now,
                "completed_at": now,
            },
            "findings": [],
        },
        ("POST", f"{base}/v1/responsibility/scan-runs/scan-1/cancel"): {
            "scan_id": "scan-1",
            "status": "cancelled",
            "execution_mode": "async",
            "scan_mode": "incremental",
            "base_scan_id": "scan-0",
            "incremental_since_at": now,
            "requested_identity_ids": ["id-a"],
            "window_hours": 48,
            "max_hops": 5,
            "min_score_threshold": 8.0,
            "retry_max_attempts": 3,
            "retry_backoff_seconds": 30,
            "current_attempt": 0,
            "claimed_by": "runner-1",
            "claimed_at": now,
            "lease_expires_at": None,
            "last_heartbeat_at": None,
            "started_at": None,
            "next_retry_at": None,
            "last_error": None,
            "cancelled_at": now,
            "cancel_reason": "manual-cancel",
            "total_identities": 0,
            "flagged_identities": 0,
            "created_at": now,
            "completed_at": None,
        },
        ("POST", f"{base}/v1/responsibility/scan-runs/scan-dlq-1/requeue"): {
            "scan_id": "scan-dlq-1",
            "status": "pending",
            "execution_mode": "async",
            "scan_mode": "incremental",
            "base_scan_id": "scan-0",
            "incremental_since_at": now,
            "requested_identity_ids": ["id-z"],
            "window_hours": 48,
            "max_hops": 5,
            "min_score_threshold": 8.0,
            "retry_max_attempts": 1,
            "retry_backoff_seconds": 30,
            "current_attempt": 0,
            "claimed_by": None,
            "claimed_at": None,
            "lease_expires_at": None,
            "last_heartbeat_at": None,
            "started_at": None,
            "next_retry_at": None,
            "last_error": "requeued from dead-letter",
            "cancelled_at": None,
            "cancel_reason": None,
            "dead_lettered_at": None,
            "dead_letter_reason": None,
            "total_identities": 0,
            "flagged_identities": 0,
            "created_at": now,
            "completed_at": None,
        },
        ("POST", f"{base}/v1/responsibility/reports/export"): {
            "report_id": "report-1",
            "target": "identity",
            "identity_id": "id-a",
            "task_id": None,
            "window_hours": 48,
            "max_hops": 5,
            "generated_at": now,
            "content_hash": "e" * 64,
            "score_summary": {
                "identity_id": "id-a",
                "window_hours": 48,
                "model_version": "public-risk-v1",
                "weighted_points": 12.4,
                "normalized_score": 12.4,
                "signal_count": 2,
                "signal_type_counts": {"mutual_exchange": 1, "cycle_authorization": 1},
                "severity_counts": {"medium": 1, "high": 1},
                "risk_band": "elevated",
                "computed_at": now,
            },
            "path_features": {
                "identity_id": "id-a",
                "window_hours": 48,
                "max_hops": 5,
                "traversed_edge_count": 4,
                "reachable_identity_count": 3,
                "cycle_paths_detected": 1,
                "path_hashes_sample": ["d" * 64],
                "computed_at": now,
            },
            "task_path_summary": None,
            "temporal_consistency": None,
            "top_signals": ingest_payload["signals"],
            "findings_excerpt": [
                {
                    "finding_id": "finding-1",
                    "scan_id": "scan-1",
                    "identity_id": "id-a",
                    "normalized_score": 12.4,
                    "risk_band": "elevated",
                    "signal_count": 2,
                    "cycle_paths_detected": 1,
                    "detail": "window_score=12.40, signals=2, cycles=1",
                    "created_at": now,
                }
            ],
            "signature": {
                "signature_scheme": "ed25519-public-placeholder",
                "signer_identity_id": "signer-1",
                "signature_payload_hash": "f" * 64,
                "signature": "sig-value",
                "status": "provided",
                "verification_note": "public signature verification placeholder only",
            },
        },
    }
    mock_http = _MockHTTP(routes)
    client = KarmaClient(agent_id="a1", runtime_url=base)
    client._http = lambda: mock_http  # type: ignore[method-assign]

    ingest = await client.ingest_responsibility_edge(
        source_identity_id="id-a",
        target_identity_id="id-b",
        edge_type=ResponsibilityEdgeType.TASK_DELEGATION,
        task_id=task_id,
    )
    assert ingest.edge.edge_hash == "a" * 64
    assert len(ingest.signals) == 1

    signals = await client.list_responsibility_signals("id-a", limit=10)
    assert signals[0].signal_type.value == "mutual_exchange"

    summary = await client.get_task_path_hash(task_id)
    assert summary.path_hash == "c" * 64
    temporal = await client.get_task_temporal_consistency(task_id)
    assert temporal.is_consistent is False
    features = await client.get_responsibility_path_features("id-a", window_hours=48, max_hops=5)
    assert features.cycle_paths_detected == 1
    score = await client.get_responsibility_score("id-a", window_hours=48)
    assert score.risk_band.value == "elevated"
    model = await client.get_public_responsibility_risk_model()
    assert model.model_version == "public-risk-v1"
    scan = await client.create_responsibility_batch_scan(
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.INCREMENTAL,
        base_scan_id="scan-0",
        window_hours=48,
        max_hops=5,
    )
    assert scan.run.scan_id == "scan-1"
    assert scan.run.execution_mode.value == "async"
    assert scan.run.scan_mode.value == "incremental"
    scan_read = await client.get_responsibility_batch_scan("scan-1", findings_limit=20)
    assert scan_read.findings[0].identity_id == "id-a"
    scan_events = await client.list_responsibility_batch_scan_events("scan-1", limit=20)
    assert scan_events[0].event_type.value == "created"
    assert scan_events[1].event_type.value == "execution_completed"
    claimed = await client.claim_responsibility_batch_scan(runner_identity_id="runner-1")
    assert claimed.status.value == "claimed"
    queue_stats = await client.get_responsibility_scan_queue_stats()
    assert queue_stats.total_runs == 5
    ops_report = await client.get_responsibility_scan_ops_report()
    assert ops_report.dead_letter_count == 1
    assert ops_report.top_failure_reasons[0].reason == "base scan run not found"
    assert ops_report.runner_activity[0].runner_identity_id == "runner-1"
    assert ops_report.alerts[0].alert_type.value == "queue_dead_letter_pressure"
    runner_activity = await client.list_responsibility_scan_runner_activity(window_hours=24, limit=20)
    assert runner_activity[0].execution_completed_count == 1
    alerts = await client.get_responsibility_scan_ops_alerts(window_hours=24, runner_limit=20)
    assert alerts[0].severity.value == "high"
    recovered_stale = await client.recover_stale_responsibility_batch_scans(limit=100)
    assert recovered_stale.recovered_scan_ids == ["scan-1"]
    dead_letter_runs = await client.list_dead_letter_responsibility_batch_scans(limit=20)
    assert dead_letter_runs[0].status.value == "dead_letter"
    swept = await client.sweep_dead_letter_responsibility_batch_scans(limit=100, reason="retry exhausted")
    assert swept.dead_lettered_count == 1
    requeued_batch = await client.requeue_dead_letter_responsibility_batch_scans(limit=100, reason="ops-batch")
    assert requeued_batch.requeued_scan_ids == ["scan-dlq-1"]
    purged = await client.purge_dead_letter_responsibility_batch_scans(limit=100, older_than_hours=72)
    assert purged.purged_scan_ids == ["scan-dlq-0"]
    pull_executed = await client.pull_execute_responsibility_batch_scan(
        runner_identity_id="runner-1",
        include_failed=True,
    )
    assert pull_executed.outcome.value == "completed"
    maintenance = await client.run_responsibility_scan_queue_maintenance_tick(
        runner_identity_id="runner-ops",
    )
    assert maintenance.executed_count == 1
    heartbeated = await client.heartbeat_responsibility_batch_scan(
        "scan-1",
        runner_identity_id="runner-1",
    )
    assert heartbeated.claimed_by == "runner-1"
    executed = await client.execute_responsibility_batch_scan(
        "scan-1",
        runner_identity_id="runner-1",
    )
    assert executed.run.current_attempt == 1
    retried = await client.retry_responsibility_batch_scan("scan-1")
    assert retried.run.current_attempt == 2
    cancelled = await client.cancel_responsibility_batch_scan(
        "scan-1",
        runner_identity_id="runner-1",
        reason="manual-cancel",
    )
    assert cancelled.status.value == "cancelled"
    requeued = await client.requeue_dead_letter_responsibility_batch_scan(
        "scan-dlq-1",
        reason="ops-requeue",
    )
    assert requeued.status.value == "pending"
    report = await client.export_explainable_risk_report(
        identity_id="id-a",
        signer_identity_id="signer-1",
        signature="sig-value",
        window_hours=48,
        max_hops=5,
    )
    assert report.report_id == "report-1"
    assert report.signature and report.signature.status.value == "provided"

