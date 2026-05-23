"""🔴 State Machine Security Tests — verify the five iron rules.

These tests are THE most important tests in the billing layer.
If any of them fail, the billing state machine has a security vulnerability.
"""

import asyncio

import pytest

from packages.karma_billing.schema import (
    BillingState,
    StateTransitionRecord,
    ScenarioType,
    ReceiptType,
)
from packages.karma_billing.state_transitions import (
    BILLING_STATE_TRANSITIONS,
    ALLOWED_STATE_PATHS,
)
from packages.karma_billing.state_machine import (
    ImmutableBillingStateMachine,
    InMemoryAuditLog,
    IllegalStateTransitionError,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def create_sm() -> ImmutableBillingStateMachine:
    """Create a fresh state machine with in-memory audit log."""
    return ImmutableBillingStateMachine(audit_log=InMemoryAuditLog())


async def execute_valid_transition(
    sm: ImmutableBillingStateMachine,
    task_id: str,
    scenario: ScenarioType,
    to_state: BillingState,
    receipt_id: str,
    did: str = "did:karma:test_agent",
) -> StateTransitionRecord:
    """Execute a single valid transition after registering receipt."""
    await sm.register_receipt(task_id, receipt_id)
    return await sm.execute_transition(
        task_id=task_id,
        scenario=scenario,
        to_state=to_state,
        triggered_by_receipt_id=receipt_id,
        triggered_by_did=did,
    )


# ── Test: Valid Transitions ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_s1_happy_path():
    """All legal S1 transitions succeed."""
    sm = create_sm()
    task_id = "task-s1-happy"
    scenario = ScenarioType.S1_DELEGATION
    did = "did:karma:test"

    path = [
        BillingState.INTENT_RECEIVED,
        BillingState.INTENT_VALIDATED,
        BillingState.DELEGATION_ACCEPTED,
        BillingState.TASK_STARTED,
        BillingState.STEP_IN_PROGRESS,
        BillingState.STEP_COMPLETED,
        BillingState.TASK_COMPLETED,
        BillingState.INVOICE_GENERATED,
        BillingState.PAYMENT_AUTHORIZED,
        BillingState.PAYMENT_PENDING,
        BillingState.PAYMENT_SETTLING,
        BillingState.SETTLED,
    ]

    for i, state in enumerate(path):
        receipt_id = f"receipt-{i:03d}"
        await sm.register_receipt(task_id, receipt_id)
        record = await sm.execute_transition(
            task_id=task_id,
            scenario=scenario,
            to_state=state,
            triggered_by_receipt_id=receipt_id,
            triggered_by_did=did,
        )
        assert record.to_state == state

    # Final state is SETTLED
    current = await sm.get_current_state(task_id)
    assert current == BillingState.SETTLED


@pytest.mark.asyncio
async def test_valid_s2_bidding_path():
    """S2 bidding transitions succeed."""
    sm = create_sm()
    task_id = "task-s2"
    scenario = ScenarioType.S2_BIDDING
    did = "did:karma:bidder"

    path = [
        BillingState.INTENT_RECEIVED,
        BillingState.INTENT_VALIDATED,
        BillingState.BID_EVALUATING,
        BillingState.BID_ACCEPTED,
        BillingState.TASK_STARTED,
        BillingState.STEP_IN_PROGRESS,
        BillingState.STEP_COMPLETED,
        BillingState.TASK_COMPLETED,
        BillingState.INVOICE_GENERATED,
        BillingState.PAYMENT_AUTHORIZED,
        BillingState.PAYMENT_SETTLING,
        BillingState.SETTLED,
    ]

    for i, state in enumerate(path):
        receipt_id = f"r-s2-{i:03d}"
        record = await execute_valid_transition(sm, task_id, scenario, state, receipt_id, did)
        assert record.to_state == state


@pytest.mark.asyncio
async def test_valid_s8_dispute_path():
    """S8 dispute with refund path succeeds."""
    sm = create_sm()
    task_id = "task-s8"
    scenario = ScenarioType.S8_DISPUTE
    did = "did:karma:disputant"

    # Normal flow to PAYMENT_SETTLING
    normal = [
        BillingState.INTENT_RECEIVED,
        BillingState.INTENT_VALIDATED,
        BillingState.DELEGATION_ACCEPTED,
        BillingState.TASK_STARTED,
        BillingState.TASK_COMPLETED,
        BillingState.INVOICE_GENERATED,
        BillingState.PAYMENT_AUTHORIZED,
        BillingState.PAYMENT_SETTLING,
    ]
    for i, state in enumerate(normal):
        receipt_id = f"r-s8-{i:03d}"
        await execute_valid_transition(sm, task_id, scenario, state, receipt_id, did)

    # Refund path
    await execute_valid_transition(sm, task_id, scenario, BillingState.REFUND_PENDING, "r-s8-refund", did)
    await execute_valid_transition(sm, task_id, scenario, BillingState.SETTLED, "r-s8-final", did)

    current = await sm.get_current_state(task_id)
    assert current == BillingState.SETTLED


# ── Test: Illegal Transitions Blocked ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_illegal_transition_blocked_global():
    """Transition not in BILLING_STATE_TRANSITIONS is rejected."""
    sm = create_sm()
    task_id = "task-illegal"
    receipt_id = "r-illegal"
    await sm.register_receipt(task_id, receipt_id)

    # SETTLED → INITIATED (reverse transition)
    # First get to SETTLED normally
    scenario = ScenarioType.S1_DELEGATION
    path = [
        BillingState.INTENT_RECEIVED,
        BillingState.INTENT_VALIDATED,
        BillingState.DELEGATION_ACCEPTED,
        BillingState.TASK_STARTED,
        BillingState.STEP_IN_PROGRESS,
        BillingState.STEP_COMPLETED,
        BillingState.TASK_COMPLETED,
        BillingState.INVOICE_GENERATED,
        BillingState.PAYMENT_AUTHORIZED,
        BillingState.PAYMENT_PENDING,
        BillingState.PAYMENT_SETTLING,
        BillingState.SETTLED,
    ]
    for i, state in enumerate(path):
        rid = f"r-setup-{i:03d}"
        await sm.register_receipt(task_id, rid)
        await sm.execute_transition(
            task_id=task_id, scenario=scenario, to_state=state,
            triggered_by_receipt_id=rid, triggered_by_did="did:karma:test",
        )

    # Attempt illegal reverse transition: SETTLED → PAYMENT_SETTLING
    await sm.register_receipt(task_id, "r-reverse")
    with pytest.raises(IllegalStateTransitionError):
        await sm.execute_transition(
            task_id=task_id,
            scenario=scenario,
            to_state=BillingState.PAYMENT_SETTLING,
            triggered_by_receipt_id="r-reverse",
            triggered_by_did="did:karma:test",
        )

    # State should still be SETTLED
    current = await sm.get_current_state(task_id)
    assert current == BillingState.SETTLED


@pytest.mark.asyncio
async def test_illegal_transition_logs_security_event():
    """Illegal transition attempts are logged as CRITICAL security events."""
    audit = InMemoryAuditLog()
    sm = ImmutableBillingStateMachine(audit_log=audit)
    task_id = "task-security"
    receipt_id = "r-security"
    await sm.register_receipt(task_id, receipt_id)

    # Try to jump from INITIATED → SETTLED directly
    is_valid = await sm.validate_transition(
        task_id=task_id,
        scenario=ScenarioType.S1_DELEGATION,
        from_state=BillingState.INITIATED,
        to_state=BillingState.SETTLED,
        triggered_by_receipt_id=receipt_id,
        triggered_by_did="did:karma:attacker",
    )
    assert is_valid is False

    # Security event logged
    assert len(audit.security_events) >= 1
    event = audit.security_events[0]
    assert event["severity"] == "CRITICAL"
    assert event["event_type"] == "ILLEGAL_TRANSITION_ATTEMPT"


@pytest.mark.asyncio
async def test_s2_transition_not_allowed_in_s1_scenario():
    """BID_EVALUATING is not on S1's path."""
    sm = create_sm()
    task_id = "task-s1-nobid"
    await sm.register_receipt(task_id, "r-1")

    # Initiate S1
    await sm.execute_transition(
        task_id=task_id, scenario=ScenarioType.S1_DELEGATION,
        to_state=BillingState.INTENT_RECEIVED,
        triggered_by_receipt_id="r-1", triggered_by_did="did:karma:seller",
    )

    # Try S2-only transition
    await sm.register_receipt(task_id, "r-2")
    with pytest.raises(IllegalStateTransitionError):
        await sm.execute_transition(
            task_id=task_id,
            scenario=ScenarioType.S1_DELEGATION,
            to_state=BillingState.BID_EVALUATING,
            triggered_by_receipt_id="r-2",
            triggered_by_did="did:karma:seller",
        )


# ── 🔴 Iron Rule 1: No admin_override / force_transition ──────────────────────


def test_admin_override_does_not_exist():
    """force_transition / admin_override / bypass_validation do not exist."""
    sm = create_sm()

    # These method names should NOT exist on the state machine
    forbidden_methods = [
        "force_transition",
        "admin_override",
        "bypass_validation",
        "update_history",
        "delete_history",
        "rollback_state",
        "emergency_reset",
        "migrate_state",
    ]

    for method_name in forbidden_methods:
        assert not hasattr(sm, method_name), (
            f"⚠️ SECURITY VIOLATION: {method_name}() should NOT exist "
            f"on ImmutableBillingStateMachine"
        )

    # Verify the only operational methods are the intended ones
    assert hasattr(sm, "validate_transition")
    assert hasattr(sm, "execute_transition")


# ── 🔴 Iron Rule 2: INSERT-only history ───────────────────────────────────────


@pytest.mark.asyncio
async def test_state_history_append_only():
    """History is only appended to — no modification of past records."""
    audit = InMemoryAuditLog()
    sm = ImmutableBillingStateMachine(audit_log=audit)
    task_id = "task-history"

    # Execute several transitions
    for i in range(5):
        receipt_id = f"r-hist-{i}"
        await sm.register_receipt(task_id, receipt_id)
        state = [
            BillingState.INTENT_RECEIVED,
            BillingState.INTENT_VALIDATED,
            BillingState.DELEGATION_ACCEPTED,
            BillingState.TASK_STARTED,
            BillingState.STEP_IN_PROGRESS,
        ][i]
        await sm.execute_transition(
            task_id=task_id,
            scenario=ScenarioType.S1_DELEGATION,
            to_state=state,
            triggered_by_receipt_id=receipt_id,
            triggered_by_did="did:karma:test",
        )

    # History should have 5 records
    assert len(audit.transitions) == 5

    # Verify no UPDATE/DELETE semantics — records are immutable
    first_record = audit.transitions[0]
    assert first_record.from_state == BillingState.INITIATED
    assert first_record.to_state == BillingState.INTENT_RECEIVED

    # Attempting to "modify" the audit log list doesn't change the stored records
    # The InMemoryAuditLog returns copies via the transitions property
    copy_list = audit.transitions
    copy_list.clear()
    # Original should be untouched
    assert len(audit.transitions) == 5


# ── 🔴 Iron Rule 3: Attempted tampering → alarm + log ─────────────────────────


@pytest.mark.asyncio
async def test_security_event_logged_on_illegal_attempt():
    """Every illegal transition attempt creates a CRITICAL security event."""
    audit = InMemoryAuditLog()
    sm = ImmutableBillingStateMachine(audit_log=audit)
    task_id = "task-alarm"
    receipt_id = "r-alarm"
    await sm.register_receipt(task_id, receipt_id)

    # Attempt multiple illegal transitions
    illegal_attempts = [
        # Jump from INITIATED to SETTLED
        (BillingState.INITIATED, BillingState.SETTLED),
        # Backwards transition
        (BillingState.INITIATED, BillingState.TASK_COMPLETED),
        # Non-existent transition
        (BillingState.INITIATED, BillingState.REFUND_PENDING),
    ]

    for from_s, to_s in illegal_attempts:
        await sm.validate_transition(
            task_id=task_id,
            scenario=ScenarioType.S1_DELEGATION,
            from_state=from_s,
            to_state=to_s,
            triggered_by_receipt_id=receipt_id,
            triggered_by_did="did:karma:attacker",
        )

    # Each illegal attempt should be logged
    assert len(audit.security_events) == len(illegal_attempts)
    for event in audit.security_events:
        assert event["severity"] == "CRITICAL"


# ── 🔴 Iron Rule 4: State history is append-only ──────────────────────────────


@pytest.mark.asyncio
async def test_history_not_modifiable_after_record():
    """Once a transition is recorded, it cannot be altered."""
    audit = InMemoryAuditLog()
    sm = ImmutableBillingStateMachine(audit_log=audit)

    record = StateTransitionRecord(
        record_id="immutable-001",
        task_id="task-x",
        from_state=BillingState.INITIATED,
        to_state=BillingState.INTENT_RECEIVED,
        triggered_by_receipt_id="r-x",
        triggered_by_did="did:karma:test",
    )
    await audit.log_transition(record)

    # The record stored in the audit log is a copy — the original is unchanged
    stored = audit.transitions[0]
    assert stored.record_id == "immutable-001"

    # Even if we modify the returned record, it doesn't affect stored data
    stored.record_id = "hacked"
    still_stored = audit.transitions[0]
    assert still_stored.record_id == "immutable-001"  # Copy is unchanged


# ── 🔴 Iron Rule 5: Concurrent transition safety ──────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_transition_safety():
    """Concurrent transitions on the same task are serialized via asyncio.Lock."""
    sm = create_sm()
    task_id = "task-concurrent"

    # Register several receipts
    for i in range(10):
        await sm.register_receipt(task_id, f"r-conc-{i}")

    # Attempt concurrent transitions
    async def do_transition(i: int) -> None:
        state = BillingState.INTENT_RECEIVED  # only the first should succeed
        try:
            await sm.execute_transition(
                task_id=task_id,
                scenario=ScenarioType.S1_DELEGATION,
                to_state=state,
                triggered_by_receipt_id=f"r-conc-{i}",
                triggered_by_did=f"did:karma:agent-{i}",
            )
        except IllegalStateTransitionError:
            pass  # Expected for concurrent attempts after the first

    tasks = [do_transition(i) for i in range(10)]
    await asyncio.gather(*tasks)

    # Only one transition should succeed (INITIATED → INTENT_RECEIVED)
    current = await sm.get_current_state(task_id)
    assert current == BillingState.INTENT_RECEIVED

    # The subsequent attempts should fail because:
    # they try INTENT_RECEIVED → INTENT_RECEIVED (self-loop), which is not allowed
    audit = sm._audit_log
    assert isinstance(audit, InMemoryAuditLog)
    # At least some attempts should have been logged as security events
    assert len(audit.security_events) >= 1


@pytest.mark.asyncio
async def test_duplicate_transition_prevented():
    """Cannot transition to the same state twice in a row."""
    sm = create_sm()
    task_id = "task-dup"
    await sm.register_receipt(task_id, "r-1")
    await sm.register_receipt(task_id, "r-2")

    # First transition: INITIATED → INTENT_RECEIVED
    await sm.execute_transition(
        task_id=task_id,
        scenario=ScenarioType.S1_DELEGATION,
        to_state=BillingState.INTENT_RECEIVED,
        triggered_by_receipt_id="r-1",
        triggered_by_did="did:karma:test",
    )

    # Second attempt: INTENT_RECEIVED → INTENT_RECEIVED (self-loop not allowed)
    with pytest.raises(IllegalStateTransitionError):
        await sm.execute_transition(
            task_id=task_id,
            scenario=ScenarioType.S1_DELEGATION,
            to_state=BillingState.INTENT_RECEIVED,
            triggered_by_receipt_id="r-2",
            triggered_by_did="did:karma:test",
        )


# ── Test: Unregistered Receipt Blocked ────────────────────────────────────────


@pytest.mark.asyncio
async def test_unregistered_receipt_blocked():
    """Transition triggered by an unregistered receipt is rejected."""
    sm = create_sm()
    task_id = "task-unreg"

    with pytest.raises(IllegalStateTransitionError):
        await sm.execute_transition(
            task_id=task_id,
            scenario=ScenarioType.S1_DELEGATION,
            to_state=BillingState.INTENT_RECEIVED,
            triggered_by_receipt_id="nonexistent-receipt",
            triggered_by_did="did:karma:attacker",
        )


# ── Test: Snapshot ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_mid_flow():
    """Snapshot reflects current state mid-flow."""
    sm = create_sm()
    task_id = "task-snap"

    for i, state in enumerate([
        BillingState.INTENT_RECEIVED,
        BillingState.INTENT_VALIDATED,
        BillingState.DELEGATION_ACCEPTED,
    ]):
        receipt_id = f"r-snap-{i}"
        await sm.register_receipt(task_id, receipt_id)
        await sm.execute_transition(
            task_id=task_id,
            scenario=ScenarioType.S1_DELEGATION,
            to_state=state,
            triggered_by_receipt_id=receipt_id,
            triggered_by_did="did:karma:test",
        )

    snap = await sm.get_snapshot(task_id)
    assert snap is not None
    assert snap.billing_state == BillingState.DELEGATION_ACCEPTED
    assert snap.current_step > 0


# ── Test: Transition Map Completeness ─────────────────────────────────────────


def test_transition_map_covers_all_states():
    """Every BillingState (except SETTLED) has an entry in the transition map."""
    for state in BillingState:
        if state == BillingState.SETTLED:
            continue
        assert state in BILLING_STATE_TRANSITIONS, (
            f"Missing transition map entry for {state.value}"
        )


def test_all_scenarios_have_allowed_paths():
    """Every ScenarioType has at least one allowed state path."""
    for scenario in ScenarioType:
        assert scenario in ALLOWED_STATE_PATHS, (
            f"Missing allowed path for scenario {scenario.value}"
        )
        assert len(ALLOWED_STATE_PATHS[scenario]) >= 1, (
            f"Empty allowed paths for scenario {scenario.value}"
        )
