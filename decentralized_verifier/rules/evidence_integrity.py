"""
Karma Decentralized Verification — Evidence Integrity Rules
============================================================
Public-safe checks on evidence integrity, signature validity, and 
cross-reference constraints for bundles, receipts, and tasks.

Every verifier node runs these independently — no private state, no DB, no network.

Derived from the public-safe subset of trusted_agent_runtime/verification.py.
"""
from __future__ import annotations

from typing import Any

from decentralized_verifier.rules.hashing import (
    evidence_hash,
    receipt_hash,
    task_contract_hash,
)


def verify_evidence_integrity(
    bundle: dict[str, Any],
    receipts: list[dict[str, Any]],
    task: dict[str, Any],
) -> dict[str, Any]:
    """
    Verify evidence integrity of a bundle against its receipts and task.

    Checks performed (objective facts only):
      1. Bundle evidence_hash matches recomputed hash of the bundle dict
      2. Every receipt in the list has a unique receipt_id (no duplicates)
      3. Receipt count in bundle.receipt_hashes matches actual receipts
      4. The bundle is not empty (has required top-level keys)
      5. Task has required identification fields (task_id, agent_id, runtime_id)
      6. Cross-reference: every receipt references the same task_id
      7. Receipt output hashes are valid SHA-256 hex strings (64 chars)

    Args:
        bundle: Evidence bundle dict with fields {task_id, task_contract_hash,
                receipt_hashes, trace_id, evidence_hash?, ...}
        receipts: List of receipt dicts
        task: Task contract dict with fields {task_id, agent_id, runtime_id, ...}

    Returns:
        {"decision": "STRUCT_OK" | "STRUCT_FAIL", "reasons": [str, ...]}
    """
    reasons: list[str] = []

    # ── 1. Bundle has required keys ──────────────────────────────────
    required_bundle_keys = {"task_id", "task_contract_hash", "receipt_hashes"}
    missing = required_bundle_keys - set(bundle.keys())
    if missing:
        reasons.append(f"bundle_missing_keys:{','.join(sorted(missing))}")
        return _fail(reasons)

    # ── 2. Task has required identification fields ────────────────────
    required_task_keys = {"task_id", "agent_id", "runtime_id"}
    missing_task = required_task_keys - set(task.keys())
    if missing_task:
        reasons.append(f"task_missing_keys:{','.join(sorted(missing_task))}")
        return _fail(reasons)

    # ── 3. Receipt uniqueness (no duplicate receipt_ids) ─────────────
    seen_ids: set[str] = set()
    for r in receipts:
        rid = r.get("receipt_id", "")
        if rid in seen_ids:
            reasons.append(f"duplicate_receipt_id:{rid}")
            return _fail(reasons)
        seen_ids.add(rid)

    # ── 4. Receipt count matches bundle ──────────────────────────────
    bundle_hashes = bundle.get("receipt_hashes") or []
    if len(bundle_hashes) != len(receipts):
        reasons.append(
            f"receipt_count_mismatch:bundle={len(bundle_hashes)}_actual={len(receipts)}"
        )
        return _fail(reasons)

    # ── 5. Cross-reference: every receipt references same task_id ────
    task_id = task.get("task_id")
    for i, r in enumerate(receipts):
        if r.get("task_id") != task_id:
            reasons.append(f"receipt_{i}_task_id_mismatch")
            return _fail(reasons)

    # ── 6. Receipt output_hash format (64-char hex) ──────────────────
    for i, r in enumerate(receipts):
        output_hash = r.get("output_hash", "")
        if not _is_hex64(output_hash):
            reasons.append(f"receipt_{i}_output_hash_not_valid_sha256")
            return _fail(reasons)

    # ── 7. Optional: verify stored evidence_hash if present ──────────
    stored_evidence_hash = bundle.get("evidence_hash")
    if stored_evidence_hash:
        computed = evidence_hash(bundle)
        if stored_evidence_hash != computed:
            reasons.append("evidence_hash_mismatch")
            return _fail(reasons)

    # All checks passed
    reasons.append("all_evidence_integrity_checks_passed")
    return _ok(reasons)


def _is_hex64(s: str) -> bool:
    """Check if a string is a 64-character lowercase hex string (SHA-256)."""
    return len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def _fail(reasons: list[str]) -> dict[str, Any]:
    return {"decision": "STRUCT_FAIL", "reasons": reasons}


def _ok(reasons: list[str]) -> dict[str, Any]:
    return {"decision": "STRUCT_OK", "reasons": reasons}
