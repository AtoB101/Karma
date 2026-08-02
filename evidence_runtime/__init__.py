"""
Evidence Runtime — public evidence + settlement-plan layer for Karma.

Receipts, evidence bundles, structural verification, and mapping into
KarmaBilateral ``proofHash`` / lock→bind→settle semantics.
No private risk logic.
"""

from evidence_runtime.evidence_adapter import EvidenceAdapter
from evidence_runtime.operational_controls import OperationalControls
from evidence_runtime.receipt_store import InMemoryReceiptStore
from evidence_runtime.recovery import describe_receipt_chain_gaps
from evidence_runtime.schemas import ExecutionReceipt, EvidenceBundle, TaskContract, VerificationResult
from evidence_runtime.settlement_adapter import SettlementAdapter
from evidence_runtime.settlement_idempotency import SettlementIdempotencyBook, settlement_step_key
from evidence_runtime.verification import verify_evidence_bundle_structural

__all__ = [
    "ExecutionReceipt",
    "EvidenceBundle",
    "TaskContract",
    "VerificationResult",
    "InMemoryReceiptStore",
    "EvidenceAdapter",
    "verify_evidence_bundle_structural",
    "SettlementAdapter",
    "OperationalControls",
    "SettlementIdempotencyBook",
    "settlement_step_key",
    "describe_receipt_chain_gaps",
]
