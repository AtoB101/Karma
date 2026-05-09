from __future__ import annotations

import unittest

from trusted_agent_runtime.evidence_adapter import EvidenceAdapter, new_receipt_id, receipt_record_hash, task_contract_hash
from trusted_agent_runtime.hashing import karma_proof_hash_pointer
from trusted_agent_runtime.receipt_store import InMemoryReceiptStore
from trusted_agent_runtime.schemas import EvidenceBundle, ExecutionReceipt, TaskContract, VerificationResult
from trusted_agent_runtime.settlement_adapter import SettlementAdapter
from trusted_agent_runtime.verification import verify_evidence_bundle_structural


class TrustedAgentRuntimeTests(unittest.TestCase):
    def test_task_contract_hash_stable(self) -> None:
        t = TaskContract(task_id="x", agent_id="a", runtime_id="r", description="d")
        h1 = task_contract_hash(t)
        h2 = task_contract_hash(t)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_receipt_hash_deterministic(self) -> None:
        r = ExecutionReceipt(
            receipt_id="rid",
            task_id="t",
            agent_id="a",
            runtime_id="rt",
            step_index=0,
            tool_name="tool",
            input_hash="i",
            output_hash="o",
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T00:00:01Z",
            duration_ms=1000,
            status="ok",
            error_code="",
            prev_receipt_hash="",
        )
        self.assertEqual(receipt_record_hash(r), receipt_record_hash(r))

    def test_evidence_bundle_digest_stable(self) -> None:
        b = EvidenceBundle(
            bundle_id="b1",
            task_id="t",
            task_contract_hash="c" * 64,
            receipt_hashes=["h1", "h2"],
            final_result_hash="h2",
            evidence_storage_refs=[],
            created_at="2026-01-01T00:00:00Z",
            signer="",
            signature="",
        )
        store = InMemoryReceiptStore()
        ad = EvidenceAdapter(store)
        self.assertEqual(ad.hash_evidence_bundle(b), ad.hash_evidence_bundle(b))

    def test_karma_proof_hash_format(self) -> None:
        d = "a" * 64
        ptr = karma_proof_hash_pointer(d)
        self.assertTrue(ptr.startswith("karma-ta:v1/sha256/"))
        self.assertEqual(ptr, f"karma-ta:v1/sha256/{d.lower()}")

    def test_full_flow_struct_ok(self) -> None:
        store = InMemoryReceiptStore()
        ad = EvidenceAdapter(store)
        task = TaskContract(task_id="t1", agent_id="ag", runtime_id="rt", description="")
        r1 = ExecutionReceipt(
            receipt_id=new_receipt_id(),
            task_id=task.task_id,
            agent_id=task.agent_id,
            runtime_id=task.runtime_id,
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
        store.save_receipt(r2)
        bundle = ad.build_evidence_bundle(task, [r1.receipt_id, r2.receipt_id])
        vr = verify_evidence_bundle_structural(task, bundle, store)
        self.assertEqual(vr.decision, "STRUCT_OK")
        self.assertIn("receipt_chain_valid", vr.public_reasons)

    def test_verify_fails_task_mismatch(self) -> None:
        store = InMemoryReceiptStore()
        ad = EvidenceAdapter(store)
        task = TaskContract(task_id="t1", agent_id="ag", runtime_id="rt", description="")
        other = TaskContract(task_id="t2", agent_id="ag", runtime_id="rt", description="")
        r1 = ExecutionReceipt(
            receipt_id=new_receipt_id(),
            task_id=task.task_id,
            agent_id=task.agent_id,
            runtime_id=task.runtime_id,
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
        store.save_receipt(r1)
        bundle = ad.build_evidence_bundle(task, [r1.receipt_id])
        bundle.task_id = "wrong"
        vr = verify_evidence_bundle_structural(other, bundle, store)
        self.assertEqual(vr.decision, "STRUCT_FAIL")

    def test_settlement_plan_blocked_on_fail(self) -> None:
        sa = SettlementAdapter()
        task = TaskContract(task_id="t", agent_id="a", runtime_id="r", description="")
        bundle = EvidenceBundle(
            bundle_id="b",
            task_id="t",
            task_contract_hash="0" * 64,
            receipt_hashes=[],
            final_result_hash="0" * 64,
            evidence_storage_refs=[],
            created_at="2026-01-01T00:00:00Z",
            signer="",
            signature="",
        )
        bad = VerificationResult(
            verification_id="v",
            task_id="t",
            evidence_bundle_digest="d",
            decision="STRUCT_FAIL",
            public_reasons=["x"],
            verified_at="2026-01-01T00:00:00Z",
        )
        plan = sa.build_offchain_plan(
            task,
            bundle,
            "proof",
            "0x" + "11" * 32,
            seller="0x2",
            token="0x3",
            amount_wei=1,
            deadline_unix=1,
            verify=bad,
        )
        self.assertEqual(plan["onchain_status"], "blocked_structural_failure")
        self.assertEqual(plan["recommended_calls"], [])


if __name__ == "__main__":
    unittest.main()
