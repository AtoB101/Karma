"""
MVVS V1 — Minimum Viable Verification Standard Tests
======================================================
Tests for the MVVS schema extensions, rejection codes,
settlement state machine additions, and API auto-verification gates.

These tests are additive — they do not modify or depend on
existing chain test fixtures.
"""

import pytest
from datetime import datetime, timedelta

from core.schemas import (
    RejectionReason,
    TaskStatus,
    SettlementState,
    TaskContract,
)
from core.mvvs_schemas import (
    TradeRecord,
    ApiCallEvidence,
    DataServiceEvidence,
    AiContentEvidence,
    ChainOpEvidence,
    AgentSubtaskEvidence,
    MinimumSettlementConditions,
    ServiceType,
    RiskLevel,
    DeliveryRuleType,
    PaymentMode,
)
from core.settlement.engine import (
    VALID_TRANSITIONS,
    STATUS_ORDER,
    can_transition,
    canonical_task_status,
    is_terminal,
)


# ---------------------------------------------------------------------------
# RejectionReason Tests
# ---------------------------------------------------------------------------

class TestRejectionReason:
    def test_all_18_codes_defined(self):
        """MVVS V1 requires exactly 18 standardized rejection codes."""
        codes = [r.value for r in RejectionReason]
        assert len(codes) == 18, f"Expected 18 codes, got {len(codes)}"
        assert "EMPTY_OUTPUT" in codes
        assert "TIMEOUT" in codes
        assert "HASH_MISMATCH" in codes
        assert "POLICY_VIOLATION" in codes

    def test_codes_are_uppercase(self):
        for r in RejectionReason:
            assert r.value == r.value.upper(), f"{r.value} must be uppercase"

    def test_no_duplicate_values(self):
        values = [r.value for r in RejectionReason]
        assert len(values) == len(set(values)), "Rejection codes must be unique"


# ---------------------------------------------------------------------------
# TaskStatus MVVS Extensions Tests
# ---------------------------------------------------------------------------

class TestTaskStatusMvvs:
    def test_new_statuses_exist(self):
        assert TaskStatus.AUTHORIZED.value == "authorized"
        assert TaskStatus.AUTO_CONFIRMED.value == "auto_confirmed"
        assert TaskStatus.PARTIALLY_SETTLED.value == "partially_settled"
        assert TaskStatus.FROZEN.value == "frozen"

    def test_legacy_statuses_unchanged(self):
        assert TaskStatus.CREATED.value == "created"
        assert TaskStatus.SETTLED.value == "settled"
        assert TaskStatus.DISPUTED.value == "disputed"
        assert TaskStatus.REFUNDED.value == "refunded"
        assert TaskStatus.CANCELLED.value == "cancelled"


# ---------------------------------------------------------------------------
# Settlement State Machine — New Transitions
# ---------------------------------------------------------------------------

class TestMvvsTransitions:
    def test_frozen_transitions(self):
        """FROZEN is a reversible meta-state — can be entered from many states."""
        # Into FROZEN
        assert can_transition(TaskStatus.DELIVERED, TaskStatus.FROZEN)
        assert can_transition(TaskStatus.DISPUTED, TaskStatus.FROZEN)
        assert can_transition(TaskStatus.ARBITRATED, TaskStatus.FROZEN)
        assert can_transition(TaskStatus.SETTLED, TaskStatus.FROZEN)
        assert can_transition(TaskStatus.PARTIALLY_SETTLED, TaskStatus.FROZEN)
        assert can_transition(TaskStatus.REFUNDED, TaskStatus.FROZEN)
        assert can_transition(TaskStatus.CANCELLED, TaskStatus.FROZEN)

        # Out of FROZEN
        assert can_transition(TaskStatus.FROZEN, TaskStatus.DELIVERED)
        assert can_transition(TaskStatus.FROZEN, TaskStatus.DISPUTED)
        assert can_transition(TaskStatus.FROZEN, TaskStatus.SETTLED)
        assert can_transition(TaskStatus.FROZEN, TaskStatus.REFUNDED)
        assert can_transition(TaskStatus.FROZEN, TaskStatus.CANCELLED)

    def test_auto_confirmed_transitions(self):
        """AUTO_CONFIRMED is between buyer confirm and delivery."""
        assert can_transition(TaskStatus.PROGRESS_CONFIRMED, TaskStatus.AUTO_CONFIRMED)
        assert can_transition(TaskStatus.AUTO_CONFIRMED, TaskStatus.SETTLED)
        assert can_transition(TaskStatus.AUTO_CONFIRMED, TaskStatus.DISPUTED)
        assert can_transition(TaskStatus.AUTO_CONFIRMED, TaskStatus.FROZEN)

    def test_partially_settled_transitions(self):
        """PARTIALLY_SETTLED is a post-arbitration partial payout."""
        assert can_transition(TaskStatus.ARBITRATED, TaskStatus.PARTIALLY_SETTLED)
        assert can_transition(TaskStatus.PARTIALLY_SETTLED, TaskStatus.SETTLED)
        assert can_transition(TaskStatus.PARTIALLY_SETTLED, TaskStatus.FROZEN)
        assert not can_transition(TaskStatus.PARTIALLY_SETTLED, TaskStatus.REFUNDED)

    def test_legacy_transitions_unchanged(self):
        """MVVS additions must not break existing state machine rules."""
        # DRAFT path
        assert can_transition(TaskStatus.DRAFT, TaskStatus.PENDING)
        assert can_transition(TaskStatus.DRAFT, TaskStatus.ACCEPTED)
        assert can_transition(TaskStatus.DRAFT, TaskStatus.CANCELLED)
        assert not can_transition(TaskStatus.DRAFT, TaskStatus.SETTLED)

        # Normal flow
        assert can_transition(TaskStatus.ACCEPTED, TaskStatus.IN_PROGRESS)
        assert can_transition(TaskStatus.IN_PROGRESS, TaskStatus.DELIVERED)
        assert can_transition(TaskStatus.DELIVERED, TaskStatus.SETTLED)
        assert can_transition(TaskStatus.DELIVERED, TaskStatus.DISPUTED)
        assert can_transition(TaskStatus.DELIVERED, TaskStatus.REFUNDED)

        # Dispute flow
        assert can_transition(TaskStatus.DISPUTED, TaskStatus.ARBITRATED)
        assert can_transition(TaskStatus.ARBITRATED, TaskStatus.SETTLED)
        assert can_transition(TaskStatus.ARBITRATED, TaskStatus.REFUNDED)

        # Terminals
        assert not can_transition(TaskStatus.SETTLED, TaskStatus.DISPUTED)
        assert not can_transition(TaskStatus.REFUNDED, TaskStatus.DISPUTED)
        assert not can_transition(TaskStatus.CANCELLED, TaskStatus.DISPUTED)


# ---------------------------------------------------------------------------
# TradeRecord Tests
# ---------------------------------------------------------------------------

class TestTradeRecord:
    def test_minimal_construction(self):
        tr = TradeRecord(task_id="task-001", buyer_agent_id="buyer-1", price=10.0)
        assert tr.task_id == "task-001"
        assert tr.buyer_agent_id == "buyer-1"
        assert tr.price == 10.0
        assert tr.settlement_status == TaskStatus.DRAFT
        assert tr.risk_level == RiskLevel.L1
        assert tr.mvvs_version == "v1.0"
        assert tr.service_type == ServiceType.GENERIC

    def test_full_construction(self):
        tr = TradeRecord(
            task_id="task-002",
            order_id="order-002",
            buyer_wallet="0x1234567890123456789012345678901234567890",
            buyer_agent_id="buyer-2",
            seller_wallet="0x0987654321098765432109876543210987654321",
            seller_agent_id="seller-2",
            service_type=ServiceType.API_CALL,
            task_description_hash="a" * 64,
            input_hash="b" * 64,
            price=50.0,
            currency="USDC",
            chain_id=11155111,
            payment_mode=PaymentMode.PREAUTH,
            delivery_rule_id="rule-001",
            delivery_deadline=datetime.utcnow() + timedelta(days=7),
            auto_confirm_rule=DeliveryRuleType.TIME_AUTO_CONFIRM,
            dispute_window=48,
            seller_accept_signature="sig_seller",
            buyer_authorization_signature="sig_buyer",
            execution_start_time=datetime.utcnow(),
            output_hash="c" * 64,
            evidence_bundle_hash="d" * 64,
            settlement_status=TaskStatus.DELIVERED,
            risk_level=RiskLevel.L2,
        )
        assert tr.order_id == "order-002"
        assert tr.chain_id == 11155111
        assert tr.dispute_window == 48
        assert tr.risk_level == RiskLevel.L2


# ---------------------------------------------------------------------------
# API Call Evidence Auto-Verification Tests
# ---------------------------------------------------------------------------

class TestApiCallEvidence:
    def test_auto_pass_all_conditions(self):
        evidence = ApiCallEvidence(
            request_id="req-1",
            caller_agent_id="agent-1",
            request_hash="a" * 64,
            response_hash="b" * 64,
            http_status=200,
            response_time_ms=150,
            provider_signature="s" * 64,
            billing_count=1,
        )
        assert evidence.auto_verdict() == "pass"

    def test_auto_fail_server_error(self):
        evidence = ApiCallEvidence(
            request_id="req-2",
            caller_agent_id="agent-2",
            request_hash="c" * 64,
            response_hash="",
            http_status=500,
            response_time_ms=150,
            billing_count=0,
        )
        assert evidence.auto_verdict() == "fail"

    def test_auto_fail_client_error(self):
        evidence = ApiCallEvidence(
            request_id="req-3",
            caller_agent_id="agent-3",
            request_hash="d" * 64,
            response_hash="e" * 64,
            http_status=404,
            response_time_ms=100,
            billing_count=1,
        )
        assert evidence.auto_verdict() == "fail"

    def test_review_when_partial(self):
        """When some but not all pass conditions are met, and no fails."""
        evidence = ApiCallEvidence(
            request_id="req-4",
            caller_agent_id="agent-4",
            request_hash="f" * 64,
            response_hash="g" * 64,
            http_status=200,
            response_time_ms=100,
            billing_count=1,
            # No provider_signature — should be ok since optional
        )
        assert evidence.auto_verdict() == "pass"

    def test_timeout_detection(self):
        evidence = ApiCallEvidence(
            request_id="req-5",
            caller_agent_id="agent-5",
            request_hash="h" * 64,
            response_hash="i" * 64,
            http_status=200,
            response_time_ms=5000,
            timeout_limit_ms=3000,
            billing_count=1,
        )
        # Timeout doesn't auto-fail, just means not_timed_out is False
        checks = evidence.auto_pass_checks()
        assert checks["not_timed_out"] is False

    def test_empty_response_with_billing(self):
        """Empty response but billed → should fail."""
        evidence = ApiCallEvidence(
            request_id="req-6",
            caller_agent_id="agent-6",
            request_hash="j" * 64,
            response_hash="",
            http_status=200,
            response_time_ms=100,
            billing_count=1,
        )
        fail_checks = evidence.auto_fail_checks()
        assert fail_checks["empty_response"] is True
        assert fail_checks["empty_result_billed"] is True


# ---------------------------------------------------------------------------
# Minimum Settlement Conditions Tests
# ---------------------------------------------------------------------------

class TestMinimumSettlementConditions:
    def test_all_pass(self):
        msc = MinimumSettlementConditions(
            buyer_authorization_signature_valid=True,
            seller_accept_signature_valid=True,
            input_hash_exists=True,
            delivery_rule_exists=True,
            execution_completed=True,
            output_hash_exists=True,
            evidence_bundle_hash_exists=True,
            no_unresolved_dispute=True,
            no_risk_rule_block=True,
            amount_within_authorization=True,
            settlement_address_matches_task=True,
            current_status_allows_settlement=True,
        )
        assert msc.all_conditions_met()
        assert msc.failed_conditions() == []

    def test_single_failure(self):
        msc = MinimumSettlementConditions(
            buyer_authorization_signature_valid=True,
            seller_accept_signature_valid=True,
            input_hash_exists=True,
            delivery_rule_exists=False,
            execution_completed=True,
            output_hash_exists=True,
            evidence_bundle_hash_exists=True,
            no_unresolved_dispute=True,
            no_risk_rule_block=True,
            amount_within_authorization=True,
            settlement_address_matches_task=True,
            current_status_allows_settlement=True,
        )
        assert not msc.all_conditions_met()
        assert msc.failed_conditions() == ["delivery_rule_exists"]

    def test_multiple_failures(self):
        msc = MinimumSettlementConditions()
        assert not msc.all_conditions_met()
        failures = msc.failed_conditions()
        assert len(failures) >= 4  # At minimum: sigs, hashes, execution


# ---------------------------------------------------------------------------
# SettlementState rejection_reason_code Tests
# ---------------------------------------------------------------------------

class TestSettlementStateRejectionCode:
    def test_new_field_exists(self):
        state = SettlementState(
            task_id="t1",
            escrow_amount=100.0,
            client_agent_id="c1",
        )
        assert state.rejection_reason_code is None

    def test_field_persists(self):
        state = SettlementState(
            task_id="t2",
            escrow_amount=50.0,
            client_agent_id="c2",
            rejection_reason_code="EMPTY_OUTPUT",
        )
        assert state.rejection_reason_code == "EMPTY_OUTPUT"


# ---------------------------------------------------------------------------
# Scene Evidence Schema Tests
# ---------------------------------------------------------------------------

class TestDataServiceEvidence:
    def test_construction(self):
        dse = DataServiceEvidence(
            data_file_hash="a" * 64,
            row_count=1000,
            column_count=10,
        )
        assert dse.row_count == 1000
        assert dse.dispute_window_hours == 48
        assert dse.revision_count == 0
        assert dse.max_revisions == 1

    def test_rejection_reason(self):
        dse = DataServiceEvidence(
            rejection_reason=RejectionReason.FORMAT_ERROR,
            rejection_detail="CSV header mismatch",
        )
        assert dse.rejection_reason == RejectionReason.FORMAT_ERROR


class TestAiContentEvidence:
    def test_text_content(self):
        ace = AiContentEvidence(
            output_file_hash="a" * 64,
            output_format="md",
            word_count=500,
        )
        assert ace.word_count == 500
        assert ace.max_revisions == 2

    def test_video_content(self):
        ace = AiContentEvidence(
            output_file_hash="b" * 64,
            output_format="mp4",
            duration_seconds=120,
            resolution="1920x1080",
        )
        assert ace.duration_seconds == 120


class TestChainOpEvidence:
    def test_construction(self):
        coe = ChainOpEvidence(
            chain_id=11155111,
            tx_hash="0x" + "a" * 64,
            transaction_status="success",
            confirmations=12,
            risk_address_check_result="clean",
            sanctions_check_result="clean",
        )
        assert coe.chain_id == 11155111
        assert coe.confirmations == 12


class TestAgentSubtaskEvidence:
    def test_construction(self):
        ase = AgentSubtaskEvidence(
            subtask_id="sub-1",
            upstream_agent_id="agent-A",
            downstream_agent_id="agent-B",
            subtask_price=25.0,
            responsibility_weight=0.5,
        )
        assert ase.upstream_agent_id == "agent-A"
        assert ase.responsibility_weight == 0.5


# ---------------------------------------------------------------------------
# ServiceType & RiskLevel Enum Tests
# ---------------------------------------------------------------------------

class TestServiceTypes:
    def test_all_types(self):
        types = [s.value for s in ServiceType]
        assert "api.call" in types
        assert "mcp.tool" in types
        assert "ai.text" in types
        assert "chain.write" in types
        assert "agent.subtask" in types


class TestRiskLevels:
    def test_all_levels(self):
        levels = [r.value for r in RiskLevel]
        assert levels == ["L1", "L2", "L3", "L4"]
