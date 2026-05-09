from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from trusted_agent_runtime.hashing import canonical_json_bytes, karma_proof_hash_pointer, sha256_hex
from trusted_agent_runtime.receipt_store import InMemoryReceiptStore
from trusted_agent_runtime.schemas import EvidenceBundle, ExecutionReceipt, TaskContract


def task_contract_hash(task: TaskContract) -> str:
    """32-byte digest as 64-char hex (SHA256 of canonical task contract). Not EVM keccak; valid bytes32-sized."""
    payload = {
        "agent_id": task.agent_id,
        "description": task.description,
        "runtime_id": task.runtime_id,
        "schema_version": task.schema_version,
        "task_id": task.task_id,
    }
    return sha256_hex(canonical_json_bytes(payload))


class EvidenceAdapter:
    """Builds evidence bundles and maps them into existing Karma `proofHash` pointer semantics."""

    def __init__(self, store: InMemoryReceiptStore) -> None:
        self._store = store

    def build_evidence_bundle(
        self,
        task: TaskContract,
        receipt_ids: list[str],
        *,
        evidence_storage_refs: list[str] | None = None,
    ) -> EvidenceBundle:
        receipts: list[ExecutionReceipt] = []
        for rid in receipt_ids:
            r = self._store.get_receipt(rid)
            if r is None:
                raise KeyError(f"missing receipt: {rid}")
            receipts.append(r)
        receipt_hashes = [receipt_record_hash(r) for r in receipts]
        final_hash = receipt_hashes[-1] if receipt_hashes else sha256_hex(b"empty")

        now = _utc_iso()
        bundle = EvidenceBundle(
            bundle_id=str(uuid.uuid4()),
            task_id=task.task_id,
            task_contract_hash=task_contract_hash(task),
            receipt_hashes=receipt_hashes,
            final_result_hash=final_hash,
            evidence_storage_refs=list(evidence_storage_refs or []),
            created_at=now,
            signer="",
            signature="",
        )
        return bundle

    def hash_evidence_bundle(self, bundle: EvidenceBundle) -> str:
        return sha256_hex(canonical_json_bytes(bundle.to_canonical_dict()))

    def map_to_karma_proof_hash(self, bundle: EvidenceBundle) -> str:
        digest = self.hash_evidence_bundle(bundle)
        return karma_proof_hash_pointer(digest)


def receipt_record_hash(receipt: ExecutionReceipt) -> str:
    return sha256_hex(canonical_json_bytes(receipt.to_canonical_dict()))


def new_receipt_id() -> str:
    return secrets.token_hex(16)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
