"""Execution/progress receipt validation guardrails."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from core.schemas import EvidenceBundle, ExecutionReceipt, ProgressReceipt
from services.receipt_canonical import (
    evidence_bundle_signing_bytes,
    execution_receipt_signing_bytes,
    progress_receipt_signing_bytes,
)
from services.receipt_templates import validate_extension_payloads
from services.signing import signing_service
from config.settings import settings

_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")

_DEV_PLACEHOLDER_SIGNATURE_PREFIXES = (
    "0xopenclaw_",
    "0xtrade_pipeline_",
    "sig-",
    "sig_",
    "runtime:",
)


def _is_production_env() -> bool:
    return (settings.app_env or "").lower() in ("production", "prod")


def delivery_signatures_relaxed() -> bool:
    """
    Local Phase 1 / OpenClaw: when trade launch EIP-712 is off, allow placeholder
    execution/progress signatures (never in production).

    Explicit: ``OPENCLAW_RELAX_DELIVERY_SIGNATURES=true|false``.

    Auto (non-production only): ``OPENCLAW_LOCAL_PHASE1_AUTO_RELAX=true`` and
    ``TRADE_LAUNCH_REQUIRE_EIP712=false`` (see ``deploy/.env.local-openclaw.example``).
    """
    if _is_production_env():
        return False
    explicit = settings.openclaw_relax_delivery_signatures
    if explicit is not None:
        return explicit
    return (
        settings.openclaw_local_phase1_auto_relax
        and not settings.trade_launch_require_eip712
    )


def _is_dev_placeholder_signature(value: str) -> bool:
    v = (value or "").strip().lower()
    if not v:
        return False
    return any(v.startswith(p) for p in _DEV_PLACEHOLDER_SIGNATURE_PREFIXES)


def _utc_aware(dt: datetime) -> datetime:
    """Normalize to UTC with tzinfo=timezone.utc (avoids naive vs aware comparisons)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def progress_timestamp_regressed(*, new_timestamp: datetime, latest_timestamp: datetime) -> bool:
    """Incoming progress timestamp older than the stored one?

    DB rows are naive UTC while a client may send a tz-aware ISO string; comparing
    the two directly raises TypeError and turns a 409 into an HTTP 500.
    """
    return _utc_aware(new_timestamp) < _utc_aware(latest_timestamp)

def execution_receipt_starts_before_prior_ended(*, started_at: datetime, prior_ended_at: datetime) -> bool:
    """
    True when the new receipt starts strictly before the prior receipt ended.

    PostgreSQL/SQLite often round-trip ``DateTime`` as naive; clients may send
    RFC3339 with ``Z``. Comparing naive vs aware raises TypeError unless normalized.
    """
    return _utc_aware(started_at) < _utc_aware(prior_ended_at)


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

    require_sig = settings.receipt_require_signature and not delivery_signatures_relaxed()
    if require_sig and not (receipt.signature or "").strip():
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
    if delivery_signatures_relaxed():
        sig = (receipt.signature or "").strip()
        if not sig or _is_dev_placeholder_signature(sig):
            return True
    if not settings.receipt_require_signature:
        if not (receipt.signature or "").strip():
            return True
    return verify_execution_receipt_signature(receipt)


_RUNTIME_BINDING_PREFIX = "runtime:"


def is_runtime_binding_signature(signature: str | None) -> bool:
    """``runtime:<sig>`` 是 Runtime Gateway 现场签发的绑定戳（不是客户端签名）。"""
    return (signature or "").strip().lower().startswith(_RUNTIME_BINDING_PREFIX)


def verify_progress_receipt_signature(progress: ProgressReceipt) -> bool:
    """进度回执验签（P1-6）。

    此前全项目**没有**这个函数：进度回执的 ``seller_signature`` 只被检查
    「非空」，随便填一个字符串就能通过，于是「卖家签过的进度」是假的。
    """
    signature = (progress.seller_signature or "").strip()
    if not signature or is_runtime_binding_signature(signature):
        return False
    return signing_service.verify(progress_receipt_signing_bytes(progress), signature)


def progress_receipt_signature_acceptable(
    progress: ProgressReceipt, *, runtime_binding_trusted: bool = False
) -> bool:
    """进度回执签名是否可接受。

    规则（与执行回执同一套口径）：

    * ``runtime:...``：只有 Runtime Gateway 现场盖章才可信 —— 走 HTTP 直连伪造
      这个前缀一律不接受（``runtime_binding_trusted`` 由路由层根据
      ``request.state`` 判定后传入）。
    * 非生产环境：允许 ``sig-`` / ``0xopenclaw_`` 这类开发占位签名（空签名也放行，
      由 ``progress_require_signature`` 决定是否强制）；**生产环境永不接受占位**。
    * 其余情况：必须能用规范载荷验签通过。
    """
    signature = (progress.seller_signature or "").strip()
    if is_runtime_binding_signature(signature):
        return bool(runtime_binding_trusted)
    if not _is_production_env() and (not signature or _is_dev_placeholder_signature(signature)):
        return True
    if not settings.progress_require_signature and not signature:
        return True
    return verify_progress_receipt_signature(progress)


def validate_progress_receipt_static(progress: ProgressReceipt) -> None:
    if not _is_hex_64(progress.evidence_hash):
        raise ValueError("progress evidence_hash must be 64-char lowercase hex")
    if not _is_hex_64(progress.runtime_log_hash):
        raise ValueError("progress runtime_log_hash must be 64-char lowercase hex")
    require_sig = settings.progress_require_signature and not delivery_signatures_relaxed()
    if require_sig and not (progress.seller_signature or "").strip():
        raise ValueError("progress seller_signature is required")

    now = datetime.now(timezone.utc)
    ts = _utc_aware(progress.timestamp)
    max_future = now + timedelta(seconds=max(0, settings.receipt_max_future_skew_seconds))
    min_past = now - timedelta(hours=max(1, settings.receipt_max_past_hours))
    if ts > max_future:
        raise ValueError("progress timestamp is too far in the future")
    if ts < min_past:
        raise ValueError("progress timestamp is too far in the past")

def verify_evidence_bundle_signature(bundle: EvidenceBundle) -> bool:
    """证据包验签（P0-5）。

    此前全项目**没有任何证据包验签函数**，``agent_signature`` 也只被当作
    可选字段原样落库 —— 于是"卖方签过这个包"这件事从未被验证过。
    """
    signature = (bundle.agent_signature or "").strip()
    if not signature or _is_dev_placeholder_signature(signature):
        return False
    return signing_service.verify(evidence_bundle_signing_bytes(bundle), signature)


def evidence_bundle_signature_acceptable(bundle: EvidenceBundle) -> bool:
    """证据包签名是否可接受（P0-5）。

    规则与执行回执同一套口径，且**生产环境永不接受占位签名**：

    * 生产环境：必须能用规范载荷验签通过。
    * 非生产环境：允许空签名或 ``sig-`` / ``0xopenclaw_`` 这类开发占位签名
      （由 ``receipt_require_signature`` 决定是否强制非空），其余一律要验签 ——
      也就是说，本地开发也挡得住"随便编一个字符串"的伪造。
    """
    signature = (bundle.agent_signature or "").strip()
    if _is_production_env():
        return verify_evidence_bundle_signature(bundle)
    if not signature or _is_dev_placeholder_signature(signature):
        return True
    return verify_evidence_bundle_signature(bundle)


def evidence_bundle_signature_required() -> bool:
    """生产口径下证据包签名是否必填（P0-5）。"""
    return bool(settings.receipt_require_signature) and not delivery_signatures_relaxed()

