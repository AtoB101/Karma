#!/usr/bin/env python3
"""
Minimal Trusted Agent flow (Phase 2) — offchain, InMemory receipts only.

create task → simulate tools → receipts → chain → evidence bundle →
proofHash mapping → structural verify → settlement plan (no chain tx).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from trusted_agent_runtime.evidence_adapter import EvidenceAdapter, new_receipt_id, receipt_record_hash, task_contract_hash
from trusted_agent_runtime.receipt_store import InMemoryReceiptStore
from trusted_agent_runtime.schemas import ExecutionReceipt, TaskContract
from trusted_agent_runtime.settlement_adapter import SettlementAdapter
from trusted_agent_runtime.verification import verify_evidence_bundle_structural


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--output-dir",
        default="results/trusted-agent-demo",
        help="Directory for JSON artifacts (default: results/trusted-agent-demo)",
    )
    args = p.parse_args()
    out = Path(args.output_dir)

    store = InMemoryReceiptStore()
    adapter = EvidenceAdapter(store)
    settlement = SettlementAdapter()

    task = TaskContract(
        task_id="task-demo-001",
        agent_id="agent-0x0001",
        runtime_id="runtime-openmanus-stub",
        description="Trusted data task (demo)",
    )
    _write(out / "task_contract.json", task.__dict__)

    # Simulated tool execution: two steps
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
    prev_h = receipt_record_hash(r1)
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
        prev_receipt_hash=prev_h,
    )
    store.save_receipt(r2)

    chain = store.get_receipt_chain(task.task_id)
    _write(
        out / "receipt_chain.json",
        {"receipts": [c.__dict__ for c in chain]},
    )

    bundle = adapter.build_evidence_bundle(task, [r1.receipt_id, r2.receipt_id])
    proof_hash = adapter.map_to_karma_proof_hash(bundle)
    _write(out / "evidence_bundle.json", bundle.__dict__)

    verify = verify_evidence_bundle_structural(task, bundle, store)
    _write(out / "verification_result.json", verify.__dict__)

    scope_hex = "0x" + task_contract_hash(task)
    plan = settlement.build_offchain_plan(
        task,
        bundle,
        proof_hash,
        scope_hex,
        seller="0x000000000000000000000000000000000000dEaD",
        token="0x000000000000000000000000000000000000c0ffee",
        amount_wei=1_000_000,
        deadline_unix=2_000_000_000,
        verify=verify,
    )
    _write(out / "settlement_result.json", plan)

    print("OK  Trusted Agent minimal flow")
    print(f"    output: {out.resolve()}")
    print(f"    proof_hash: {proof_hash}")
    print(f"    bundle_digest: {adapter.hash_evidence_bundle(bundle)}")
    print(f"    verification: {verify.decision} {verify.public_reasons}")


if __name__ == "__main__":
    main()
