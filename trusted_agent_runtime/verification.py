from __future__ import annotations

import uuid
from datetime import datetime, timezone

from trusted_agent_runtime.evidence_adapter import receipt_record_hash, task_contract_hash
from trusted_agent_runtime.hashing import canonical_json_bytes, sha256_hex
from trusted_agent_runtime.receipt_store import InMemoryReceiptStore
from trusted_agent_runtime.schemas import EvidenceBundle, TaskContract, VerificationResult


def verify_evidence_bundle_structural(
    task: TaskContract,
    bundle: EvidenceBundle,
    store: InMemoryReceiptStore,
) -> VerificationResult:
    """
    Structural checks only (public-safe). No risk scoring or private policy.
    """
    reasons: list[str] = []
    verified_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    bundle_digest = sha256_hex(canonical_json_bytes(bundle.to_canonical_dict()))

    if bundle.task_id != task.task_id:
        reasons.append("task_id_mismatch")
        return _result(bundle_digest, bundle.task_id, "STRUCT_FAIL", reasons, verified_at)

    if bundle.task_contract_hash != task_contract_hash(task):
        reasons.append("task_contract_hash_mismatch")
        return _result(bundle_digest, bundle.task_id, "STRUCT_FAIL", reasons, verified_at)

    chain = store.get_receipt_chain(task.task_id)
    if not chain:
        reasons.append("receipt_missing")
        return _result(bundle_digest, bundle.task_id, "STRUCT_FAIL", reasons, verified_at)

    chain_sorted = sorted(chain, key=lambda r: (r.step_index, r.receipt_id))
    expected_hashes = [receipt_record_hash(r) for r in chain_sorted]
    if expected_hashes != bundle.receipt_hashes:
        reasons.append("hash_mismatch")
        return _result(bundle_digest, bundle.task_id, "STRUCT_FAIL", reasons, verified_at)

    # Chronological sanity (ISO8601 string compare works for same format Z)
    last = ""
    for r in chain_sorted:
        if r.started_at < last:
            reasons.append("chronological_error")
            return _result(bundle_digest, bundle.task_id, "STRUCT_FAIL", reasons, verified_at)
        last = r.started_at

    reasons.append("receipt_chain_valid")
    return _result(bundle_digest, bundle.task_id, "STRUCT_OK", reasons, verified_at)


def _result(
    bundle_digest: str,
    task_id: str,
    decision: str,
    reasons: list[str],
    verified_at: str,
) -> VerificationResult:
    return VerificationResult(
        verification_id=str(uuid.uuid4()),
        task_id=task_id,
        evidence_bundle_digest=bundle_digest,
        decision=decision,  # type: ignore[arg-type]
        public_reasons=reasons,
        verified_at=verified_at,
    )
