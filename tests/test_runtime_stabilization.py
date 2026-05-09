from __future__ import annotations

import unittest

from trusted_agent_runtime.demo_payload import build_demo_offchain_bundle
from trusted_agent_runtime.evidence_adapter import EvidenceAdapter, new_receipt_id, receipt_record_hash
from trusted_agent_runtime.operational_controls import OperationalControls
from trusted_agent_runtime.receipt_store import InMemoryReceiptStore
from trusted_agent_runtime.recovery import describe_receipt_chain_gaps
from trusted_agent_runtime.schemas import EvidenceBundle, ExecutionReceipt, TaskContract, VerificationResult
from trusted_agent_runtime.settlement_adapter import SettlementAdapter
from trusted_agent_runtime.settlement_idempotency import SettlementIdempotencyBook
from trusted_agent_runtime.verification import verify_evidence_bundle_structural


class RuntimeStabilizationTests(unittest.TestCase):
    def test_trace_id_propagates_demo_payload(self) -> None:
        p = build_demo_offchain_bundle(trace_id="trace-unit-1")
        self.assertEqual(p["task"]["trace_id"], "trace-unit-1")
        self.assertEqual(p["evidence_bundle"]["trace_id"], "trace-unit-1")
        self.assertEqual(p["verification"]["trace_id"], "trace-unit-1")

    def test_pause_verification_blocks(self) -> None:
        p = build_demo_offchain_bundle(trace_id="t-verify-pause")
        store = InMemoryReceiptStore()
        for r in p["receipt_chain"]["receipts"]:
            store.save_receipt(ExecutionReceipt(**r))
        task = TaskContract(**p["task"])
        bundle = EvidenceBundle(**p["evidence_bundle"])
        ctr = OperationalControls(pause_verification=True)
        vr = verify_evidence_bundle_structural(task, bundle, store, controls=ctr)
        self.assertEqual(vr.decision, "STRUCT_FAIL")
        self.assertIn("pause_verification", vr.public_reasons)

    def test_pause_settlement_empty_calls(self) -> None:
        p = build_demo_offchain_bundle(trace_id="t-settle-pause")
        task = TaskContract(**p["task"])
        bundle = EvidenceBundle(**p["evidence_bundle"])
        verify = VerificationResult(**p["verification"])
        plan = SettlementAdapter().build_offchain_plan(
            task,
            bundle,
            p["proof_hash"],
            p["scope_hex"],
            seller="0x1",
            token="0x2",
            amount_wei=1,
            deadline_unix=9,
            verify=verify,
            controls=OperationalControls(pause_settlement=True),
        )
        self.assertEqual(plan["recommended_calls"], [])
        self.assertIn("operational_blocked", plan["onchain_status"])

    def test_pause_payout_omits_request(self) -> None:
        p = build_demo_offchain_bundle(trace_id="t-payout-pause")
        task = TaskContract(**p["task"])
        bundle = EvidenceBundle(**p["evidence_bundle"])
        verify = VerificationResult(**p["verification"])
        plan = SettlementAdapter().build_offchain_plan(
            task,
            bundle,
            p["proof_hash"],
            p["scope_hex"],
            seller="0x1",
            token="0x2",
            amount_wei=1,
            deadline_unix=9,
            verify=verify,
            controls=OperationalControls(pause_payout=True),
        )
        fns = [c["function"] for c in plan["recommended_calls"]]
        self.assertNotIn("requestBillPayout", fns)
        self.assertIn("createBill", fns)

    def test_freeze_agent_blocks_verification(self) -> None:
        p = build_demo_offchain_bundle(trace_id="t-freeze-agent")
        store = InMemoryReceiptStore()
        for r in p["receipt_chain"]["receipts"]:
            store.save_receipt(ExecutionReceipt(**r))
        task = TaskContract(**p["task"])
        bundle = EvidenceBundle(**p["evidence_bundle"])
        ctr = OperationalControls(frozen_agent_ids=frozenset({task.agent_id}))
        vr = verify_evidence_bundle_structural(task, bundle, store, controls=ctr)
        self.assertEqual(vr.decision, "STRUCT_FAIL")
        self.assertIn("freeze_agent", vr.public_reasons)

    def test_freeze_task_blocks_verification(self) -> None:
        p = build_demo_offchain_bundle(trace_id="t-freeze")
        store = InMemoryReceiptStore()
        for r in p["receipt_chain"]["receipts"]:
            store.save_receipt(ExecutionReceipt(**r))
        task = TaskContract(**p["task"])
        bundle = EvidenceBundle(**p["evidence_bundle"])
        ctr = OperationalControls(frozen_task_ids=frozenset({task.task_id}))
        vr = verify_evidence_bundle_structural(task, bundle, store, controls=ctr)
        self.assertEqual(vr.decision, "STRUCT_FAIL")
        self.assertIn("freeze_task", vr.public_reasons)

    def test_partial_receipt_chain_recovery_messages(self) -> None:
        task = TaskContract(task_id="t-partial", agent_id="a", runtime_id="r", description="", trace_id="tr")
        r0 = ExecutionReceipt(
            receipt_id="r0",
            task_id=task.task_id,
            agent_id=task.agent_id,
            runtime_id=task.runtime_id,
            trace_id=task.trace_id,
            step_index=0,
            tool_name="t",
            input_hash="0",
            output_hash="1",
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T00:00:01Z",
            duration_ms=1,
            status="ok",
            error_code="",
            prev_receipt_hash="",
        )
        r_skip = ExecutionReceipt(
            receipt_id="r2",
            task_id=task.task_id,
            agent_id=task.agent_id,
            runtime_id=task.runtime_id,
            trace_id=task.trace_id,
            step_index=2,
            tool_name="t",
            input_hash="0",
            output_hash="1",
            started_at="2026-01-01T00:00:02Z",
            ended_at="2026-01-01T00:00:03Z",
            duration_ms=1,
            status="ok",
            error_code="",
            prev_receipt_hash=receipt_record_hash(r0),
        )
        msgs = describe_receipt_chain_gaps([r0, r_skip])
        self.assertTrue(any("non_contiguous_step_index" in m for m in msgs))

    def test_save_receipt_idempotent(self) -> None:
        store = InMemoryReceiptStore()
        r = ExecutionReceipt(
            receipt_id="same",
            task_id="t",
            agent_id="a",
            runtime_id="r",
            step_index=0,
            tool_name="x",
            input_hash="0",
            output_hash="1",
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T00:00:01Z",
            duration_ms=1,
            status="ok",
            error_code="",
            prev_receipt_hash="",
        )
        store.save_receipt(r)
        store.save_receipt(r)
        self.assertEqual(len(store.get_receipt_chain("t")), 1)

    def test_save_receipt_collision_raises(self) -> None:
        store = InMemoryReceiptStore()
        base = dict(
            receipt_id="same",
            task_id="t",
            agent_id="a",
            runtime_id="r",
            step_index=0,
            tool_name="x",
            input_hash="0",
            output_hash="1",
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T00:00:01Z",
            duration_ms=1,
            status="ok",
            error_code="",
            prev_receipt_hash="",
        )
        store.save_receipt(ExecutionReceipt(**base))
        other = ExecutionReceipt(**{**base, "output_hash": "9"})
        with self.assertRaises(ValueError):
            store.save_receipt(other)

    def test_partial_store_bundle_build_raises_deterministic(self) -> None:
        """Simulates process kill after step 0: step-2 receipt never persisted → bundle build fails fast."""
        store = InMemoryReceiptStore()
        ad = EvidenceAdapter(store)
        task = TaskContract(task_id="t1", agent_id="ag", runtime_id="rt", description="", trace_id="tr1")
        r1 = ExecutionReceipt(
            receipt_id=new_receipt_id(),
            task_id=task.task_id,
            agent_id=task.agent_id,
            runtime_id=task.runtime_id,
            trace_id=task.trace_id,
            step_index=0,
            tool_name="t0",
            input_hash="0",
            output_hash="1",
            started_at="2026-05-01T10:00:00Z",
            ended_at="2026-05-01T10:00:01Z",
            duration_ms=1,
            status="ok",
            error_code="",
            prev_receipt_hash="",
        )
        r2 = ExecutionReceipt(
            receipt_id=new_receipt_id(),
            task_id=task.task_id,
            agent_id=task.agent_id,
            runtime_id=task.runtime_id,
            trace_id=task.trace_id,
            step_index=1,
            tool_name="t1",
            input_hash="1",
            output_hash="2",
            started_at="2026-05-01T10:00:02Z",
            ended_at="2026-05-01T10:00:03Z",
            duration_ms=1,
            status="ok",
            error_code="",
            prev_receipt_hash=receipt_record_hash(r1),
        )
        store.save_receipt(r1)
        with self.assertRaises(KeyError):
            ad.build_evidence_bundle(task, [r1.receipt_id, r2.receipt_id])

    def test_settlement_idempotency_keys_duplicate(self) -> None:
        p = build_demo_offchain_bundle(trace_id="idem-1")
        task = TaskContract(**p["task"])
        bundle = EvidenceBundle(**p["evidence_bundle"])
        verify = VerificationResult(**p["verification"])
        plan = SettlementAdapter().build_offchain_plan(
            task,
            bundle,
            p["proof_hash"],
            p["scope_hex"],
            seller="0x1",
            token="0x2",
            amount_wei=1,
            deadline_unix=9,
            verify=verify,
        )
        keys = [x["idempotency_key"] for x in plan["settlement_step_keys"]]
        book = SettlementIdempotencyBook()
        first = [book.try_once(k) for k in keys]
        second = [book.try_once(k) for k in keys]
        self.assertTrue(all(first))
        self.assertFalse(any(second))

    def test_repeated_plan_same_fingerprint(self) -> None:
        p = build_demo_offchain_bundle(trace_id="idem-2")
        task = TaskContract(**p["task"])
        bundle = EvidenceBundle(**p["evidence_bundle"])
        verify = VerificationResult(**p["verification"])
        sa = SettlementAdapter()
        a = sa.build_offchain_plan(
            task, bundle, p["proof_hash"], p["scope_hex"], seller="0x1", token="0x2", amount_wei=1, deadline_unix=9, verify=verify
        )
        b = sa.build_offchain_plan(
            task, bundle, p["proof_hash"], p["scope_hex"], seller="0x1", token="0x2", amount_wei=1, deadline_unix=9, verify=verify
        )
        self.assertEqual(a["settlement_step_keys"], b["settlement_step_keys"])


if __name__ == "__main__":
    unittest.main()
