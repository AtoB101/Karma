"""
Karma Decentralized Verification — Structural Rules
====================================================
Public-safe structural checks on evidence bundles and receipts.

These verify objective format, ordering, hash consistency, and trace integrity.
Every verifier node runs these independently — no private state, no DB, no network.

Derived from the public-safe subset of trusted_agent_runtime/verification.py.
"""
from __future__ import annotations

from typing import Any

from decentralized_verifier.rules.hashing import receipt_hash, task_contract_hash


def structural_verify(
    task: dict[str, Any],
    bundle: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Verify structural integrity of an evidence bundle against its task and receipts.

    Checks performed (objective facts only, no quality/business judgment):
      1. task_id matches bundle.task_id
      2. task_contract_hash (recomputed) matches bundle.task_contract_hash
      3. receipt chain exists (receipts list is non-empty)
      4. receipt hashes in bundle match recomputed hashes from receipt dicts
      5. chronological order — started_at is strictly ascending
      6. trace_id consistency — if task.trace_id is set, bundle and all receipts match
      7. output_hash is present (non-empty) on every receipt
      8. step_index is sequential (no gaps, starts from 0)

    Args:
        task: Task contract dict with fields {task_id, agent_id, runtime_id, ...}
        bundle: Evidence bundle dict with fields {task_id, task_contract_hash,
                receipt_hashes, trace_id, ...}
        receipts: List of receipt dicts, each with {receipt_id, step_index, started_at,
                  output_hash, trace_id, ...}

    Returns:
        {"decision": "STRUCT_OK" | "STRUCT_FAIL", "reasons": [str, ...]}
    """
    reasons: list[str] = []

    # ── 1. task_id match ──────────────────────────────────────────────
    if bundle.get("task_id") != task.get("task_id"):
        reasons.append("task_id_mismatch")
        return _fail(reasons)

    # ── 2. task_contract_hash match ───────────────────────────────────
    computed_tc_hash = task_contract_hash(task)
    if bundle.get("task_contract_hash") != computed_tc_hash:
        reasons.append("task_contract_hash_mismatch")
        return _fail(reasons)

    # ── 3. receipt chain exists ───────────────────────────────────────
    if not receipts:
        reasons.append("receipt_chain_empty")
        return _fail(reasons)

    # ── 4. receipt hashes match recomputed hashes ─────────────────────
    # Sort receipts for deterministic ordering: by step_index, then receipt_id
    sorted_receipts = sorted(
        receipts, key=lambda r: (r.get("step_index", 0), r.get("receipt_id", ""))
    )
    expected_hashes = [receipt_hash(r) for r in sorted_receipts]
    bundle_hashes = bundle.get("receipt_hashes") or []
    if expected_hashes != bundle_hashes:
        reasons.append("receipt_hash_mismatch")
        return _fail(reasons)

    # ── 5. chronological order (started_at ascending) ─────────────────
    last_started_at = ""
    for r in sorted_receipts:
        started_at = r.get("started_at", "")
        if not started_at:
            continue
        if started_at < last_started_at:
            reasons.append("chronological_order_violation")
            return _fail(reasons)
        last_started_at = started_at

    # ── 6. trace_id consistency ───────────────────────────────────────
    task_trace_id = task.get("trace_id")
    if task_trace_id:
        if bundle.get("trace_id") != task_trace_id:
            reasons.append("bundle_trace_id_mismatch")
            return _fail(reasons)
        for r in sorted_receipts:
            if r.get("trace_id") and r.get("trace_id") != task_trace_id:
                reasons.append("receipt_trace_id_mismatch")
                return _fail(reasons)

    # ── 7. output_hash present on every receipt ───────────────────────
    for i, r in enumerate(sorted_receipts):
        if not r.get("output_hash"):
            reasons.append(f"missing_output_hash_step_{i}")
            return _fail(reasons)

    # ── 8. step_index sequential (no gaps, starts from 0) ─────────────
    for i, r in enumerate(sorted_receipts):
        expected_step = i
        actual_step = r.get("step_index")
        if actual_step != expected_step:
            reasons.append(
                f"step_index_gap_at_{i}_expected_{expected_step}_got_{actual_step}"
            )
            return _fail(reasons)

    # All checks passed
    reasons.append("all_structural_checks_passed")
    return _ok(reasons)


def _fail(reasons: list[str]) -> dict[str, Any]:
    return {"decision": "STRUCT_FAIL", "reasons": reasons}


def _ok(reasons: list[str]) -> dict[str, Any]:
    return {"decision": "STRUCT_OK", "reasons": reasons}
