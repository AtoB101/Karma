"""Canonical signing payload for ExecutionReceipt (Ed25519) — single source of truth."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from core.schemas import ExecutionReceipt, ProgressReceipt


def execution_receipt_signing_dict(receipt: ExecutionReceipt) -> dict[str, Any]:
    """
    Fields included in Ed25519 signing / verification.

    Backward compatible: receipts without ``extension`` match the historical
    payload (core fields + status only). When ``extension`` is set, it is
    merged as JSON-stable dict so templates participate in integrity.
    """
    payload: dict[str, Any] = {
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
    if receipt.extension is not None:
        payload["extension"] = receipt.extension.model_dump(mode="json")
    return payload


def execution_receipt_signing_bytes(receipt: ExecutionReceipt) -> bytes:
    d = execution_receipt_signing_dict(receipt)
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str).encode()


# ---------------------------------------------------------------------------
# ProgressReceipt (P1-6 修复)
#
# 2026-09-17 复核：进度回执的 ``seller_signature`` 此前只校验「非空」，
# 全项目没有任何进度回执验签函数 —— 也就是说随便填个字符串就能过关。
# 这里给出唯一的规范签名载荷，服务端/网关/流水线都用它。
# ---------------------------------------------------------------------------

def _utc_iso(value: datetime) -> str:
    """时间戳统一成「UTC + 显式时区偏移」的 ISO 串。

    进度回执由不同实现产生（Agent SDK / Runtime 网关 / 内部流水线），
    naive 与 aware、``Z`` 与 ``+00:00``、``+08:00`` 与等价 UTC 时刻，
    必须归一到同一串字节。否则签名方与验签方会因为「表示法不同」而互不通过，
    表现为生产里莫名其妙的 400 —— 这是跨实现验签的硬要求。
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def progress_receipt_signing_dict(progress: ProgressReceipt) -> dict[str, Any]:
    return {
        "progress_receipt_id": progress.progress_receipt_id,
        "task_id": progress.task_id,
        "seller_identity_id": progress.seller_identity_id,
        "progress_percent": progress.progress_percent,
        "claimed_value_percent": progress.claimed_value_percent,
        "evidence_hash": progress.evidence_hash,
        "runtime_log_hash": progress.runtime_log_hash,
        "timestamp": _utc_iso(progress.timestamp),
        "validation_method": progress.validation_method,
    }


def progress_receipt_signing_bytes(progress: ProgressReceipt) -> bytes:
    d = progress_receipt_signing_dict(progress)
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str).encode()

# ---------------------------------------------------------------------------
# EvidenceBundle (P0-5 修复)
#
# 规范载荷定义在 ``core.evidence.bundle_builder``（该模块是公开 SDK 面，
# 不能反向依赖 services）；这里只做再导出，保证服务端只有一条来源。
# ---------------------------------------------------------------------------
from core.evidence.bundle_builder import (  # noqa: E402  (re-export)
    evidence_bundle_signing_bytes,
    evidence_bundle_signing_dict,
)

__all__ = [
    "execution_receipt_signing_dict",
    "execution_receipt_signing_bytes",
    "progress_receipt_signing_dict",
    "progress_receipt_signing_bytes",
    "evidence_bundle_signing_dict",
    "evidence_bundle_signing_bytes",
]
