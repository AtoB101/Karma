"""Execution/progress receipt validation guardrails."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from core.schemas import ExecutionReceipt, ProgressReceipt
from services.receipt_canonical import execution_receipt_signing_bytes
from services.receipt_templates import validate_extension_payloads
from services.signing import signing_service
from config.settings import settings

_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


def _utc_aware(dt: datetime) -> datetime:
    """Normalize to UTC with tzinfo=timezone.utc (avoids naive vs aware comparisons)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_hex_64(value: str) -> bool:
    return bool(_HEX_64_RE.fullmatch((value or "").lower()))


def validate_execution_receipt_static(receipt: ExecutionReceipt) -> None:
    if not _is_hex_64(receipt.input_hash):
        raise ValueError("input_hash must be 64-char lowercase hex")
    if not _is_hex_64(receipt.output_hash):
        raise ValueError("output_hash must be 64-char lowercase hex")

    started = _utc_aware(receipt.started_at)
    ended = _utc_aware(receipt.ended_at)
    if ended < started:
        raise ValueError("receipt ended_at must be >= started_at")

    if receipt.extension is not None:
        validate_extension_payloads(receipt.extension)

    now = datetime.now(timezone.utc)
    max_future = now + timedelta(seconds=max(0, settings.receipt_max_future_skew_seconds))
    past_hours = (
        max(1, settings.receipt_max_past_hours_strict)
        if settings.receipt_strict_recent_timestamps
        else max(1, settings.receipt_max_past_hours)
    )
    min_past = now - timedelta(hours=past_hours)
    if started > max_future or ended > max_future:
        raise ValueError("receipt timestamp is too far in the future")
    if started < min_past:
        raise ValueError("receipt timestamp is too far in the past")

    expected_duration = int((ended - started).total_seconds() * 1000)
    if abs(expected_duration - receipt.duration_ms) > 5_000:
        raise ValueError("receipt duration_ms does not match timestamp delta")

    if settings.receipt_require_signature and not (receipt.signature or "").strip():
        raise ValueError("receipt signature is required")


def verify_execution_receipt_signature(receipt: ExecutionReceipt) -> bool:
    """Return True only when a non-empty signature verifies against canonical bytes."""
    signature = (receipt.signature or "").strip()
    if not signature:
        return False
    raw = execution_receipt_signing_bytes(receipt)
    return signing_service.verify(raw, signature)


def execution_receipt_signature_acceptable(receipt: ExecutionReceipt) -> bool:
    """
    HTTP-layer gate: respects ``receipt_require_signature``.

    When signatures are optional, an absent signature is accepted; if the client
    sends one, it must verify. When required, presence is enforced by
    ``validate_execution_receipt_static`` and this delegates to
    ``verify_execution_receipt_signature``.
    """
    if not settings.receipt_require_signature:
        if not (receipt.signature or "").strip():
            return True
    return verify_execution_receipt_signature(receipt)


def validate_progress_receipt_static(progress: ProgressReceipt) -> None:
    if not _is_hex_64(progress.evidence_hash):
        raise ValueError("progress evidence_hash must be 64-char lowercase hex")
    if not _is_hex_64(progress.runtime_log_hash):
        raise ValueError("progress runtime_log_hash must be 64-char lowercase hex")
    if settings.progress_require_signature and not (progress.seller_signature or "").strip():
        raise ValueError("progress seller_signature is required")

    now = datetime.now(timezone.utc)
    ts = _utc_aware(progress.timestamp)
    max_future = now + timedelta(seconds=max(0, settings.receipt_max_future_skew_seconds))
    min_past = now - timedelta(hours=max(1, settings.receipt_max_past_hours))
    if ts > max_future:
        raise ValueError("progress timestamp is too far in the future")
    if ts < min_past:
        raise ValueError("progress timestamp is too far in the past")
