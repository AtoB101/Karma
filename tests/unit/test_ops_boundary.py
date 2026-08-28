from __future__ import annotations

import pytest

from services.ops_boundary import (
    OpsFundsBoundaryError,
    assert_offchain_payout_marks_allowed,
    assert_ops_may_submit_funds,
)
from services.runtime_safety import get_runtime_safety_mode_state
from services.security_control_plane import (
    classify_and_maybe_freeze,
    clear_control_plane_state,
)


def test_ops_cannot_submit_funds_when_flag_off(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "chain_allow_ops_submit_funds", False)
    with pytest.raises(OpsFundsBoundaryError, match="settle"):
        assert_ops_may_submit_funds("settle")


def test_ops_may_submit_funds_when_flag_on(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "chain_allow_ops_submit_funds", True)
    assert_ops_may_submit_funds("settle")


def test_offchain_payout_marks_blocked(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "ops_allow_offchain_payout_marks", False)
    with pytest.raises(OpsFundsBoundaryError, match="off-chain"):
        assert_offchain_payout_marks_allowed("offchain_mark_refunded")


def test_critical_freeze_pauses_runtime_ops():
    clear_control_plane_state()
    try:
        classify_and_maybe_freeze(
            classification="ops_brake",
            severity="critical",
            actor_id="admin-1",
            reason="incident",
            submit_on_chain=False,
        )
        state = get_runtime_safety_mode_state()
        assert state.pause_new_lock is True
        assert state.pause_new_settlement is True
    finally:
        clear_control_plane_state()


def test_adapter_refund_blocked_when_ops_funds_disabled(monkeypatch):
    from datetime import datetime, timedelta

    from core.schemas import (
        TaskContract,
        VerificationCheck,
        VerificationDecision,
        VerificationResult,
    )
    from services.chain.settlement_adapter import OnChainSettlementAdapter

    monkeypatch.setattr(
        "config.settings.settings.chain_allow_ops_submit_funds",
        False,
    )
    adapter = OnChainSettlementAdapter()
    contract = TaskContract(
        task_id="t1",
        client_agent_id="c",
        worker_agent_id="w",
        title="t",
        description="d",
        expected_output_schema={},
        expected_step_count=1,
        escrow_amount=1,
        deadline_at=datetime.utcnow() + timedelta(hours=1),
        onchain_binding_id=1,
    )
    verification = VerificationResult(
        task_id="t1",
        bundle_id="b1",
        decision=VerificationDecision.REFUND,
        confidence=1.0,
        checks=[VerificationCheck(name="n", passed=True)],
        notes="test",
    )
    with pytest.raises(OpsFundsBoundaryError):
        adapter.refund_payment("t1", verification, task_contract=contract)
