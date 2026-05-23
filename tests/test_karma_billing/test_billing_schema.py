"""Tests for billing schema — UniversalReceipt, hashing, enums."""

import hashlib
import json
import uuid
from datetime import datetime, timezone

import pytest

from packages.karma_billing.schema import (
    ScenarioType,
    ReceiptStatus,
    ReceiptType,
    BillingState,
    UniversalReceipt,
    BillingSnapshot,
    StateTransitionRecord,
    compute_payload_hash,
    compute_leaf_hash,
)


# ── Enums ─────────────────────────────────────────────────────────────────────


def test_scenario_type_values():
    """All 10 scenario types are defined."""
    assert len(ScenarioType) == 10
    assert ScenarioType.S1_DELEGATION.value == "S1_DELEGATION"
    assert ScenarioType.S10_CROSS_CHAIN.value == "S10_CROSS_CHAIN"


def test_receipt_status_flow():
    """Receipt status lifecycle order."""
    statuses = list(ReceiptStatus)
    assert statuses == [
        ReceiptStatus.GENERATED,
        ReceiptStatus.ANCHORING,
        ReceiptStatus.ANCHORED,
        ReceiptStatus.VERIFIED,
    ]


def test_billing_state_count():
    """Exactly 17 billing states defined."""
    assert len(BillingState) == 17


def test_receipt_type_count():
    """At least 40 receipt types across all scenarios."""
    assert len(ReceiptType) >= 40


# ── Hashing ───────────────────────────────────────────────────────────────────


def test_compute_payload_hash_deterministic():
    """Same data produces same hash."""
    data = {"amount": 100, "currency": "USDC"}
    h1 = compute_payload_hash(data)
    h2 = compute_payload_hash(data)
    assert h1 == h2
    assert len(h1) == 64  # SHA256 hex digest


def test_compute_payload_hash_order_independent():
    """Dict key order does not affect hash (canonical JSON)."""
    d1 = {"b": 2, "a": 1}
    d2 = {"a": 1, "b": 2}
    assert compute_payload_hash(d1) == compute_payload_hash(d2)


def test_compute_payload_hash_different_data():
    """Different data produces different hashes."""
    h1 = compute_payload_hash({"x": 1})
    h2 = compute_payload_hash({"x": 2})
    assert h1 != h2


def test_compute_leaf_hash_deterministic():
    """Leaf hash is deterministic."""
    args = ("r1", "t1", 0, "abc123", "2024-01-01T00:00:00+00:00")
    h1 = compute_leaf_hash(*args)
    h2 = compute_leaf_hash(*args)
    assert h1 == h2
    assert len(h1) == 32  # SHA256 raw bytes


def test_compute_leaf_hash_structurally_distinct():
    """Leaf hash distinguishes different receipts."""
    h1 = compute_leaf_hash("r1", "t1", 0, "abc", "2024-01-01T00:00:00+00:00")
    h2 = compute_leaf_hash("r2", "t1", 0, "abc", "2024-01-01T00:00:00+00:00")
    assert h1 != h2


# ── UniversalReceipt ──────────────────────────────────────────────────────────


def make_receipt(**overrides) -> UniversalReceipt:
    """Create a test UniversalReceipt with sensible defaults."""
    defaults = {
        "receipt_id": str(uuid.uuid4()),
        "task_id": "task-001",
        "scenario": ScenarioType.S1_DELEGATION,
        "step_index": 0,
        "generator_did": "did:karma:generator",
        "buyer_did": "did:karma:buyer",
        "seller_did": "did:karma:seller",
        "receipt_type": ReceiptType.S1_INTENT_CREATED,
        "input_hash": hashlib.sha256(b"input").hexdigest(),
        "output_hash": hashlib.sha256(b"output").hexdigest(),
        "scenario_data": {"note": "test"},
    }
    defaults.update(overrides)
    return UniversalReceipt(**defaults)


def test_universal_receipt_creation():
    """Basic receipt creation with all required fields."""
    r = make_receipt()
    assert r.receipt_id is not None
    assert r.task_id == "task-001"
    assert r.scenario == ScenarioType.S1_DELEGATION
    assert r.status == ReceiptStatus.GENERATED


def test_universal_receipt_auto_payload_hash():
    """payload_hash is auto-computed from scenario_data."""
    r = make_receipt(scenario_data={"action": "delegate", "amount": 100})
    expected = compute_payload_hash({"action": "delegate", "amount": 100})
    assert r.payload_hash == expected


def test_universal_receipt_explicit_payload_hash():
    """Explicit payload_hash is preserved."""
    r = make_receipt(payload_hash="explicit_hash_abc", scenario_data={"x": 1})
    assert r.payload_hash == "explicit_hash_abc"


def test_universal_receipt_compute_leaf():
    """Leaf hash matches expected formula."""
    r = make_receipt(
        receipt_id="rid-1",
        task_id="task-1",
        step_index=0,
        payload_hash="abc123",
    )
    leaf = r.compute_leaf()
    expected = compute_leaf_hash(
        receipt_id="rid-1",
        task_id="task-1",
        step_index=0,
        payload_hash="abc123",
        timestamp=r.created_at.isoformat(),
    )
    assert leaf == expected


def test_universal_receipt_serialization():
    """Receipt serializes to JSON correctly."""
    r = make_receipt()
    d = r.model_dump(mode="json")
    assert d["receipt_id"] == r.receipt_id
    assert d["scenario"] == "S1_DELEGATION"
    assert "created_at" in d


def test_universal_receipt_chain_linking():
    """Parent and previous hash linking works."""
    r1 = make_receipt(receipt_id="r1")
    r2 = make_receipt(
        receipt_id="r2",
        parent_receipt_id="r1",
        previous_payload_hash=r1.payload_hash,
    )
    assert r2.parent_receipt_id == "r1"
    assert r2.previous_payload_hash == r1.payload_hash


def test_universal_receipt_step_index_non_negative():
    """step_index must be >= 0."""
    with pytest.raises(Exception):  # pydantic validation error
        make_receipt(step_index=-1)


# ── BillingSnapshot ───────────────────────────────────────────────────────────


def test_billing_snapshot_creation():
    """Snapshot holds point-in-time task state."""
    snap = BillingSnapshot(
        task_id="task-001",
        scenario=ScenarioType.S1_DELEGATION,
        billing_state=BillingState.STEP_IN_PROGRESS,
        current_step=3,
        total_steps_estimated=13,
        cost_accrued_usdc=1.50,
        total_budget_usdc=10.00,
        progress_percent=23.08,
        anchored_receipts=2,
        latest_merkle_root="abc123",
        last_anchor_tx="0xdeadbeef",
    )
    assert snap.task_id == "task-001"
    assert snap.billing_state == BillingState.STEP_IN_PROGRESS
    assert snap.progress_percent == 23.08


# ── StateTransitionRecord ─────────────────────────────────────────────────────


def test_state_transition_record_creation():
    """Transition record is created with all fields."""
    rec = StateTransitionRecord(
        record_id=str(uuid.uuid4()),
        task_id="task-001",
        from_state=BillingState.INITIATED,
        to_state=BillingState.INTENT_RECEIVED,
        triggered_by_receipt_id="receipt-001",
        triggered_by_did="did:karma:agent",
    )
    assert rec.from_state == BillingState.INITIATED
    assert rec.to_state == BillingState.INTENT_RECEIVED
    assert rec.triggered_by_receipt_id == "receipt-001"


def test_state_transition_record_timestamp_auto():
    """Timestamp is auto-generated."""
    rec = StateTransitionRecord(
        record_id=str(uuid.uuid4()),
        task_id="task-001",
        from_state=BillingState.INITIATED,
        to_state=BillingState.INTENT_RECEIVED,
        triggered_by_receipt_id="r-001",
        triggered_by_did="did:karma:agent",
    )
    assert rec.timestamp is not None
