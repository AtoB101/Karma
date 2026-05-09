from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ReceiptStatus = Literal["ok", "error", "skipped"]
VerificationDecision = Literal["STRUCT_OK", "STRUCT_FAIL"]


@dataclass
class TaskContract:
    """Minimal task description (no plaintext payloads; hashes only in extensions)."""

    task_id: str
    agent_id: str
    runtime_id: str
    description: str = ""
    schema_version: str = "karma.task_contract.v1"
    trace_id: str = ""


@dataclass
class ExecutionReceipt:
    receipt_id: str
    task_id: str
    agent_id: str
    runtime_id: str
    step_index: int
    tool_name: str
    input_hash: str
    output_hash: str
    started_at: str
    ended_at: str
    duration_ms: int
    status: ReceiptStatus
    error_code: str
    evidence_refs: list[str] = field(default_factory=list)
    signer: str = ""
    signature: str = ""
    schema_version: str = "karma.execution_receipt.v1"
    prev_receipt_hash: str = ""
    trace_id: str = ""

    def to_canonical_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "agent_id": self.agent_id,
            "duration_ms": self.duration_ms,
            "ended_at": self.ended_at,
            "error_code": self.error_code,
            "evidence_refs": list(self.evidence_refs),
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "receipt_id": self.receipt_id,
            "runtime_id": self.runtime_id,
            "schema_version": self.schema_version,
            "signer": self.signer,
            "signature": self.signature,
            "started_at": self.started_at,
            "status": self.status,
            "step_index": self.step_index,
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "prev_receipt_hash": self.prev_receipt_hash,
        }
        if self.trace_id:
            d["trace_id"] = self.trace_id
        return d


@dataclass
class EvidenceBundle:
    bundle_id: str
    task_id: str
    task_contract_hash: str
    receipt_hashes: list[str]
    final_result_hash: str
    evidence_storage_refs: list[str]
    created_at: str
    signer: str
    signature: str
    schema_version: str = "karma.ta.evidence_bundle.v1"
    trace_id: str = ""

    def to_canonical_dict(self) -> dict[str, Any]:
        out = {
            "bundle_id": self.bundle_id,
            "created_at": self.created_at,
            "evidence_storage_refs": list(self.evidence_storage_refs),
            "final_result_hash": self.final_result_hash,
            "receipt_hashes": list(self.receipt_hashes),
            "schema_version": self.schema_version,
            "signature": self.signature,
            "signer": self.signer,
            "task_contract_hash": self.task_contract_hash,
            "task_id": self.task_id,
        }
        if self.trace_id:
            out["trace_id"] = self.trace_id
        return out


@dataclass
class VerificationResult:
    verification_id: str
    task_id: str
    evidence_bundle_digest: str
    decision: VerificationDecision
    public_reasons: list[str]
    verified_at: str
    verifier: str = "karma.structural.v1"
    signature: str = ""
    trace_id: str = ""
