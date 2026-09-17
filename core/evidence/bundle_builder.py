"""
Karma Trust Protocol — Evidence Bundle Builder (Public Interface)
=================================================================
Collects all ExecutionReceipts for a task and assembles them into
a signed EvidenceBundle ready for submission to the Verification Engine.

Usage
-----
    from karma.evidence import EvidenceBundleBuilder
    from karma.receipts import InMemoryReceiptStore

    builder = EvidenceBundleBuilder(receipt_store=store)
    bundle  = await builder.build(task_contract, final_result)
    await client.submit_bundle(bundle)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from core.schemas import (
    EvidenceBundle,
    ExecutionReceipt,
    TaskContract,
    TaskStatus,
    ToolStatus,
)
from core.hooks.hook_layer import ReceiptStore


def _sha256(data: Any) -> str:
    if isinstance(data, bytes):
        raw = data
    elif isinstance(data, str):
        raw = data.encode()
    else:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def execution_receipt_bundle_digest(receipt: ExecutionReceipt) -> str:
    """
    SHA-256 hex digest of a receipt as embedded in ``EvidenceBundle.receipt_hashes``.

    Must stay aligned with ``EvidenceBundleBuilder`` hashing (canonical JSON of the receipt).
    """
    return _sha256(receipt.model_dump(mode="json"))


def evidence_bundle_signing_dict(bundle: EvidenceBundle) -> dict[str, Any]:
    """证据包签名/验签的**唯一**规范载荷（P0-5）。

    字段与历史 ``EvidenceBundleBuilder`` 载荷逐字节兼容（键名沿用
    ``contract_hash``），因此既有的、用旧载荷签出来的包仍然可验；
    服务端 ``POST /v1/bundles`` 的强制验签用的也是这一份。
    """
    return {
        "task_id": bundle.task_id,
        "contract_hash": bundle.task_contract_hash,
        "receipt_hashes": list(bundle.receipt_hashes),
        "final_result_hash": bundle.final_result_hash,
        "total_steps": bundle.total_steps,
        "successful_steps": bundle.successful_steps,
        "created_at": bundle.created_at.isoformat(),
    }


def evidence_bundle_signing_bytes(bundle: EvidenceBundle) -> bytes:
    d = evidence_bundle_signing_dict(bundle)
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str).encode()


# ---------------------------------------------------------------------------
# Bundle Signer Interface
# ---------------------------------------------------------------------------

class BundleSigner:
    """
    Sign an evidence bundle with the worker agent's Ed25519 key.
    Implement in your private runtime and inject into EvidenceBundleBuilder.
    """

    def sign_bundle(self, payload: dict[str, Any]) -> str:
        """
        Sign the canonical bundle payload dict.
        Return base64-encoded Ed25519 signature.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Object Store Interface
# ---------------------------------------------------------------------------

class ObjectStore:
    """
    Abstract object store for persisting full bundles (MinIO / S3).
    Implement and inject for production deployments.
    """

    async def save_bundle(
        self,
        bundle: EvidenceBundle,
        receipts: list[ExecutionReceipt],
    ) -> str:
        """Persist the bundle + receipts. Return the storage path."""
        raise NotImplementedError

    async def load_bundle(self, storage_path: str) -> dict[str, Any]:
        """Load a bundle by its storage path."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class EvidenceBundleBuilder:
    """
    Assembles a signed EvidenceBundle from all receipts of a task.

    Parameters
    ----------
    receipt_store:  Where to fetch receipts from.
    signer:         Optional BundleSigner (required for production).
    object_store:   Optional ObjectStore for persistence.
    """

    def __init__(
        self,
        receipt_store: ReceiptStore,
        signer: Optional[BundleSigner] = None,
        object_store: Optional[ObjectStore] = None,
    ):
        self.receipt_store = receipt_store
        self.signer = signer
        self.object_store = object_store

    async def build(
        self,
        task_contract: TaskContract,
        final_result: Any,
    ) -> EvidenceBundle:
        """
        Build a complete, signed EvidenceBundle.

        Steps
        -----
        1. Load all receipts for task_id from receipt_store.
        2. Sort by step_index.
        3. Hash each receipt.
        4. Hash the final result.
        5. Sign the canonical bundle payload.
        6. Optionally persist to object store.
        7. Return the bundle.
        """
        task_id = task_contract.task_id
        receipts = await self.receipt_store.list_by_task(task_id)
        receipts.sort(key=lambda r: r.step_index)

        successful = sum(1 for r in receipts if r.status == ToolStatus.SUCCESS)
        failed = sum(1 for r in receipts if r.status == ToolStatus.FAILURE)
        total_ms = sum(r.duration_ms for r in receipts)

        receipt_hashes = [_sha256(r.model_dump(mode="json")) for r in receipts]
        receipt_ids = [r.receipt_id for r in receipts]
        final_result_hash = _sha256(final_result)
        contract_hash = task_contract.contract_hash or _sha256(
            task_contract.model_dump(mode="json"),
        )

        bundle = EvidenceBundle(
            task_id=task_id,
            task_contract_hash=contract_hash,
            receipt_ids=receipt_ids,
            receipt_hashes=receipt_hashes,
            final_result_hash=final_result_hash,
            total_steps=len(receipts),
            successful_steps=successful,
            failed_steps=failed,
            total_duration_ms=total_ms,
            created_at=datetime.utcnow(),
            settlement_status=TaskStatus.DELIVERED,
        )

        # 2026-09-17：签名载荷收敛到唯一来源，签出来的包在服务端能被真正验签。
        if self.signer:
            bundle.agent_signature = self.signer.sign_bundle(
                evidence_bundle_signing_dict(bundle)
            )

        if self.object_store:
            path = await self.object_store.save_bundle(bundle, receipts)
            bundle.storage_path = path

        return bundle
