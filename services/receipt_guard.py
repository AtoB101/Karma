"""Execution/progress receipt validation guardrails."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from core.schemas import ExecutionReceipt, ProgressReceipt
from services.signing import signing_service
from config.settings import settings

_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_hex_64(value: str) -> bool:
    return bool(_HEX_64_RE.fullmatch((value or "").lower()))


def _canonical_execution_receipt_payload(receipt: ExecutionReceipt) -> dict[str, str | int]:
    return {
        "receipt_id": receipt.receipt_id,
        "task_id": receipt.task_id,
        "agent_id": receipt.agent_id,
        "step_index": receipt.step_index,
        "tool_name": receipt.tool_name,
        "input_hash": receipt.input_hash,
        "output_hash": receipt.output_hash,
        "started_at": receipt.started_at.isoformat(),
        "ended_at": receipt.ended_at.isoformat(),
        "status": receipt.status.value if hasattr(receipt.status, "value") else str(receipt.status),
    }


def validate_execution_receipt_static(receipt: ExecutionReceipt) -> None:
    if not _is_hex_64(receipt.input_hash):
        raise ValueError("input_hash must be 64-char lowercase hex")
    if not _is_hex_64(receipt.output_hash):
        raise ValueError("output_hash must be 64-char lowercase hex")
    if receipt.ended_at < receipt.started_at:
        raise ValueError("receipt ended_at must be >= started_at")

    now = datetime.utcnow()
    max_future = now + timedelta(seconds=max(0, settings.receipt_max_future_skew_seconds))
    min_past = now - timedelta(hours=max(1, settings.receipt_max_past_hours))
    if receipt.started_at > max_future or receipt.ended_at > max_future:
        raise ValueError("receipt timestamp is too far in the future")
    if receipt.started_at < min_past:
        raise ValueError("receipt timestamp is too far in the past")

    expected_duration = int((receipt.ended_at - receipt.started_at).total_seconds() * 1000)
    if abs(expected_duration - receipt.duration_ms) > 5_000:
        raise ValueError("receipt duration_ms does not match timestamp delta")

    if settings.receipt_require_signature and not (receipt.signature or "").strip():
        raise ValueError("receipt signature is required")


def verify_execution_receipt_signature(receipt: ExecutionReceipt) -> bool:
    signature = (receipt.signature or "").strip()
    if not signature:
        return False
    payload = _canonical_execution_receipt_payload(receipt)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return signing_service.verify(raw, signature)


def validate_progress_receipt_static(progress: ProgressReceipt) -> None:
    if not _is_hex_64(progress.evidence_hash):
        raise ValueError("progress evidence_hash must be 64-char lowercase hex")
    if not _is_hex_64(progress.runtime_log_hash):
        raise ValueError("progress runtime_log_hash must be 64-char lowercase hex")
    if settings.progress_require_signature and not (progress.seller_signature or "").strip():
        raise ValueError("progress seller_signature is required")

    now = datetime.utcnow()
    max_future = now + timedelta(seconds=max(0, settings.receipt_max_future_skew_seconds))
    min_past = now - timedelta(hours=max(1, settings.receipt_max_past_hours))
    if progress.timestamp > max_future:
        raise ValueError("progress timestamp is too far in the future")
    if progress.timestamp < min_past:
        raise ValueError("progress timestamp is too far in the past")
