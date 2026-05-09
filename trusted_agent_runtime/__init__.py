"""
Trusted Agent Runtime — public integration layer on Karma.

This package is intentionally small: receipts, bundles, structural verification,
and mapping into existing Karma `proofHash` / bill semantics. No private risk logic.
"""

from trusted_agent_runtime.evidence_adapter import EvidenceAdapter
from trusted_agent_runtime.operational_controls import OperationalControls
from trusted_agent_runtime.receipt_store import InMemoryReceiptStore
from trusted_agent_runtime.recovery import describe_receipt_chain_gaps
from trusted_agent_runtime.schemas import ExecutionReceipt, EvidenceBundle, TaskContract, VerificationResult
from trusted_agent_runtime.settlement_adapter import SettlementAdapter
from trusted_agent_runtime.settlement_idempotency import SettlementIdempotencyBook, settlement_step_key
from trusted_agent_runtime.verification import verify_evidence_bundle_structural

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
