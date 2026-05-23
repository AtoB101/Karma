"""Tests for Karma Security Compliance Auditor"""
import sys, os, hashlib, uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'packages', 'karma_billing'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'packages', 'karma_security'))

import pytest
from karma_billing.schema import UniversalReceipt, ScenarioType, ReceiptType, ReceiptStatus
from karma_billing.state_machine import ImmutableBillingStateMachine
from karma_billing.state_transitions import BILLING_STATE_TRANSITIONS
from karma_security import SecurityAuditor
from karma_security.standards import (
    ReceiptIntegrityCheck, EvidenceAnchoringCheck, StateMachineSecurityCheck,
    SettlementSecurityCheck, DataPrivacyCheck, CrossScenarioCheck,
)


def _mk_receipt_dict(rid, task_id, step, rtype, buyer, seller, parent=None, signed=True):
    inp = f"in-{rid}"; out = f"out-{rid}"
    from karma_billing.schema import compute_payload_hash
    sd = {"step": step}
    return {
        "receipt_id": rid, "task_id": task_id, "scenario": "S1_DELEGATION",
        "step_index": step, "generator_did": seller, "buyer_did": buyer, "seller_did": seller,
        "receipt_type": rtype, "input_hash": hashlib.sha256(inp.encode()).hexdigest(),
        "output_hash": hashlib.sha256(out.encode()).hexdigest(),
        "payload_hash": compute_payload_hash(sd),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution_duration_ms": 50, "parent_receipt_id": parent,
        "scenario_data": sd, "status": "GENERATED",
        "signature": f"sig-{rid}" if signed else "",
    }


class TestReceiptIntegrity:
    
    def test_all_receipts_signed(self):
        receipts = [
            _mk_receipt_dict("r1", "t1", 1, "S1_INTENT_CREATED", "b", "s", signed=True),
            _mk_receipt_dict("r2", "t1", 2, "S1_STEP_EXECUTED", "b", "s", parent="r1", signed=True),
        ]
        finding = ReceiptIntegrityCheck.r1_1_signature(receipts)
        assert finding.passed

    def test_unsigned_receipt_detected(self):
        receipts = [
            _mk_receipt_dict("r1", "t1", 1, "S1_INTENT_CREATED", "b", "s", signed=False),
        ]
        finding = ReceiptIntegrityCheck.r1_1_signature(receipts)
        assert not finding.passed

    def test_unbroken_chain(self):
        receipts = [
            _mk_receipt_dict("r1", "t1", 1, "S1_INTENT_CREATED", "b", "s"),
            _mk_receipt_dict("r2", "t1", 2, "S1_STEP_EXECUTED", "b", "s", parent="r1"),
            _mk_receipt_dict("r3", "t1", 3, "S1_TASK_COMPLETED", "b", "s", parent="r2"),
        ]
        finding = ReceiptIntegrityCheck.r1_2_chain_unbroken(receipts)
        assert finding.passed

    def test_broken_chain_detected(self):
        receipts = [
            _mk_receipt_dict("r1", "t1", 1, "S1_INTENT_CREATED", "b", "s"),
            _mk_receipt_dict("r2", "t1", 2, "S1_STEP_EXECUTED", "b", "s", parent="r999"),  # wrong parent
        ]
        finding = ReceiptIntegrityCheck.r1_2_chain_unbroken(receipts)
        assert not finding.passed


class TestStateMachineSecurity:
    
    def test_no_backdoor(self):
        finding = StateMachineSecurityCheck.r3_1_no_backdoor(ImmutableBillingStateMachine)
        assert finding.passed

    def test_backdoor_detected(self):
        class BadStateMachine:
            def force_transition(self): pass
        finding = StateMachineSecurityCheck.r3_1_no_backdoor(BadStateMachine)
        assert not finding.passed


class TestDataPrivacy:
    
    def test_no_raw_data(self):
        receipts = [_mk_receipt_dict("r1", "t1", 1, "S1_INTENT_CREATED", "b", "s")]
        finding = DataPrivacyCheck.r5_1_no_raw_data(receipts)
        assert finding.passed

    def test_raw_data_detected(self):
        receipts = [{"receipt_id": "r1", "raw_input": "secret_data", "scenario_data": {}}]
        finding = DataPrivacyCheck.r5_1_no_raw_data(receipts)
        assert not finding.passed


class TestAuditorIntegration:
    
    def test_full_audit_pass(self):
        task_id = "audit-test-" + str(uuid.uuid4())[:8]
        receipts = [
            _mk_receipt_dict(f"a{i}", task_id, i, 
                           f"S1_{t}", "buyer", "seller",
                           parent=f"a{i-1}" if i > 1 else None)
            for i, t in enumerate(["INTENT_CREATED", "DELEGATION_ACCEPTED", 
                                  "TASK_STARTED", "STEP_EXECUTED", 
                                  "TASK_COMPLETED", "PAYMENT_SETTLED"], 1)
        ]

        auditor = SecurityAuditor()
        report = auditor.audit(
            receipts=receipts,
            state_machine_class=ImmutableBillingStateMachine,
            transition_table=BILLING_STATE_TRANSITIONS,
            escrow_functions=["deposit", "release", "refund"],
            amount_usdc=50.00,
        )

        assert report.score > 0
        assert report.total_checks > 0
        # R1 should pass: all signed, chained, hashed
        r1_findings = [f for f in report.findings if f.standard == "R1"]
        assert all(f.passed for f in r1_findings)
    
    def test_audit_detects_problems(self):
        # Bad receipts: unsigned, broken chain
        bad_receipts = [
            _mk_receipt_dict("b1", "t2", 1, "S1_INTENT_CREATED", "b", "s", signed=False),
            _mk_receipt_dict("b2", "t2", 2, "S1_STEP_EXECUTED", "b", "s", parent="nonexistent"),
        ]

        auditor = SecurityAuditor()
        report = auditor.audit(
            receipts=bad_receipts,
            escrow_functions=["deposit", "adminWithdraw"],  # Has forbidden function
        )

        # Should have failures
        assert report.failed > 0
        # R4.1 should fail (non-custodial check)
        r4_findings = [f for f in report.findings if f.standard == "R4"]
        assert any(not f.passed for f in r4_findings)
