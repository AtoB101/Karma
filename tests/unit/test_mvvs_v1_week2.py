"""
MVVS V1 Week 2 — Scene 4 (Chain Ops), Buyer Confirm Flow, Dashboard Tests
"""

import pytest
from datetime import datetime, timedelta

from core.schemas import TaskStatus, SettlementState
from core.mvvs_schemas import ChainOpEvidence
from core.settlement.engine import can_transition


class TestChainOpAutoVerify:
    def test_pass_successful_tx(self):
        coe = ChainOpEvidence(
            chain_id=11155111,
            tx_hash="0x" + "a" * 64,
            transaction_status="success",
            confirmations=12,
            risk_address_check_result="clean",
            sanctions_check_result="clean",
        )
        assert coe.auto_verdict() == "pass"

    def test_fail_failed_tx(self):
        coe = ChainOpEvidence(
            chain_id=11155111,
            tx_hash="0x" + "b" * 64,
            transaction_status="failed",
        )
        assert coe.auto_verdict() == "fail"

    def test_fail_sanctioned_address(self):
        coe = ChainOpEvidence(
            chain_id=1,
            tx_hash="0x" + "c" * 64,
            transaction_status="success",
            confirmations=12,
            risk_address_check_result="sanctioned",
        )
        assert coe.auto_verdict() == "fail"

    def test_fail_pending_tx(self):
        """Pending tx should fail — MVVS: no settlement without confirmation."""
        coe = ChainOpEvidence(
            chain_id=11155111,
            tx_hash="0x" + "d" * 64,
            transaction_status="pending",
        )
        assert coe.auto_verdict() == "fail"

    def test_fail_flagged_address(self):
        coe = ChainOpEvidence(
            chain_id=11155111,
            tx_hash="0x" + "e" * 64,
            transaction_status="success",
            confirmations=12,
            risk_address_check_result="flagged",
        )
        assert coe.auto_verdict() == "fail"

    def test_fail_sanctions_match(self):
        coe = ChainOpEvidence(
            chain_id=11155111,
            tx_hash="0x" + "f" * 64,
            transaction_status="success",
            confirmations=12,
            risk_address_check_result="clean",
            sanctions_check_result="match",
        )
        assert coe.auto_verdict() == "fail"

    def test_fail_event_log_mismatch(self):
        coe = ChainOpEvidence(
            chain_id=11155111,
            tx_hash="0x" + "g" * 64,
            transaction_status="success",
            confirmations=12,
            expected_event_signature="Transfer(address,address,uint256)",
            actual_event_signature="Approve(address,uint256)",
        )
        assert coe.auto_verdict() == "fail"

    def test_no_confirmations_no_pass(self):
        """Without confirmations, should not auto-pass."""
        coe = ChainOpEvidence(
            chain_id=11155111,
            tx_hash="0x" + "h" * 64,
            transaction_status="success",
            confirmations=0,
        )
        # confirmations=0 → not sufficient → should be review (not fail, not pass)
        assert coe.auto_verdict() in ("review", "fail")


class TestSettlementConfirmWindow:
    def test_confirm_window_default_none(self):
        ss = SettlementState(
            task_id="t1",
            escrow_amount=100.0,
            client_agent_id="c1",
        )
        assert ss.confirm_window_hours is None
        assert ss.confirm_deadline_at is None

    def test_confirm_window_set(self):
        ss = SettlementState(
            task_id="t2",
            escrow_amount=50.0,
            client_agent_id="c2",
            confirm_window_hours=48,
        )
        assert ss.confirm_window_hours == 48

    def test_confirm_window_valid_range(self):
        """confirm_window_hours must be 0-720 (0=instant, 720=30 days max)."""
        ss = SettlementState(
            task_id="t3",
            escrow_amount=10.0,
            client_agent_id="c3",
            confirm_window_hours=0,
        )
        assert ss.confirm_window_hours == 0


class TestAutoConfirmedTransitions:
    def test_progress_confirmed_to_auto_confirmed(self):
        assert can_transition(TaskStatus.PROGRESS_CONFIRMED, TaskStatus.AUTO_CONFIRMED)

    def test_auto_confirmed_to_settled(self):
        assert can_transition(TaskStatus.AUTO_CONFIRMED, TaskStatus.SETTLED)

    def test_auto_confirmed_to_disputed(self):
        assert can_transition(TaskStatus.AUTO_CONFIRMED, TaskStatus.DISPUTED)

    def test_auto_confirmed_to_frozen(self):
        assert can_transition(TaskStatus.AUTO_CONFIRMED, TaskStatus.FROZEN)

    def test_auto_confirmed_cannot_go_back_to_in_progress(self):
        assert not can_transition(TaskStatus.AUTO_CONFIRMED, TaskStatus.IN_PROGRESS)

    def test_auto_confirmed_cannot_go_back_to_draft(self):
        assert not can_transition(TaskStatus.AUTO_CONFIRMED, TaskStatus.DRAFT)
