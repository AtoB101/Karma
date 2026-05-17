"""Receipt signature required when RECEIPT_REQUIRE_SIGNATURE=true (production default)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.schemas import ExecutionReceipt, ToolStatus
from services import receipt_guard as rg


def _hex64() -> str:
    return "b" * 64


def test_validate_execution_receipt_rejects_missing_signature_when_required(monkeypatch):
    monkeypatch.setattr(rg.settings, "receipt_require_signature", True)
    t0 = datetime.now(timezone.utc) - timedelta(seconds=2)
    t1 = datetime.now(timezone.utc) - timedelta(seconds=1)
    r = ExecutionReceipt(
        task_id="prod-sig",
        agent_id="agent-1",
        step_index=1,
        tool_name="noop",
        input_hash=_hex64(),
        output_hash=_hex64(),
        started_at=t0,
        ended_at=t1,
        duration_ms=int((t1 - t0).total_seconds() * 1000),
        status=ToolStatus.SUCCESS,
        signature="",
    )
    with pytest.raises(ValueError, match="signature is required"):
        rg.validate_execution_receipt_static(r)


def test_validate_execution_receipt_allows_missing_signature_when_disabled(monkeypatch):
    monkeypatch.setattr(rg.settings, "receipt_require_signature", False)
    t0 = datetime.now(timezone.utc) - timedelta(seconds=2)
    t1 = datetime.now(timezone.utc) - timedelta(seconds=1)
    r = ExecutionReceipt(
        task_id="dev-sig-off",
        agent_id="agent-1",
        step_index=1,
        tool_name="noop",
        input_hash=_hex64(),
        output_hash=_hex64(),
        started_at=t0,
        ended_at=t1,
        duration_ms=int((t1 - t0).total_seconds() * 1000),
        status=ToolStatus.SUCCESS,
        signature=None,
    )
    rg.validate_execution_receipt_static(r)
