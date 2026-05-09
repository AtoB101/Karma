"""Shared demo: offchain receipts → bundle → proofHash / scope (Phase 2 + Phase 3 hybrid input)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from trusted_agent_runtime.evidence_adapter import EvidenceAdapter, new_receipt_id, receipt_record_hash, task_contract_hash
from trusted_agent_runtime.receipt_store import InMemoryReceiptStore
from trusted_agent_runtime.schemas import ExecutionReceipt, TaskContract
from trusted_agent_runtime.verification import verify_evidence_bundle_structural


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_demo_offchain_bundle(
    *,
    task_id: str = "task-demo-001",
    agent_id: str = "agent-0x0001",
    runtime_id: str = "runtime-openmanus-stub",
    description: str = "Trusted data task (demo)",
) -> dict:
    store = InMemoryReceiptStore()
    adapter = EvidenceAdapter(store)

    task = TaskContract(
        task_id=task_id,
        agent_id=agent_id,
        runtime_id=runtime_id,
        description=description,
    )

    t0 = _utc()
    r1 = ExecutionReceipt(
        receipt_id=new_receipt_id(),
        task_id=task.task_id,
        agent_id=task.agent_id,
        runtime_id=task.runtime_id,
        step_index=0,
        tool_name="fetch_dataset",
        input_hash="sha256:" + "a" * 64,
        output_hash="sha256:" + "b" * 64,
        started_at=t0,
        ended_at=t0,
        duration_ms=12,
        status="ok",
        error_code="",
        evidence_refs=[],
        prev_receipt_hash="",
    )
    store.save_receipt(r1)
    t1 = _utc()
    r2 = ExecutionReceipt(
        receipt_id=new_receipt_id(),
        task_id=task.task_id,
        agent_id=task.agent_id,
        runtime_id=task.runtime_id,
        step_index=1,
        tool_name="summarize",
        input_hash="sha256:" + "c" * 64,
        output_hash="sha256:" + "d" * 64,
        started_at=t1,
        ended_at=t1,
        duration_ms=8,
        status="ok",
        error_code="",
        evidence_refs=[],
        prev_receipt_hash=receipt_record_hash(r1),
    )
    store.save_receipt(r2)

    bundle = adapter.build_evidence_bundle(task, [r1.receipt_id, r2.receipt_id])
    proof_hash = adapter.map_to_karma_proof_hash(bundle)
    verify = verify_evidence_bundle_structural(task, bundle, store)
    scope_hex = "0x" + task_contract_hash(task)
    bundle_digest = adapter.hash_evidence_bundle(bundle)

    return {
        "task": asdict(task),
        "receipt_chain": {"receipts": [asdict(x) for x in store.get_receipt_chain(task.task_id)]},
        "evidence_bundle": asdict(bundle),
        "verification": asdict(verify),
        "proof_hash": proof_hash,
        "scope_hex": scope_hex,
        "bundle_digest": bundle_digest,
    }
