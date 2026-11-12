"""Canonical signing payload for ExecutionReceipt (Ed25519) — single source of truth."""
from __future__ import annotations

import json
from typing import Any

from core.schemas import ExecutionReceipt


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
