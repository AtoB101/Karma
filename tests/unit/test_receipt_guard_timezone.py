"""receipt_guard — naive vs aware datetime comparisons (UTC normalization)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.schemas import ExecutionReceipt, ProgressReceipt, ProgressConfirmationStatus, ToolStatus
from services import receipt_guard as rg


def _hex64() -> str:
    return "a" * 64


@pytest.fixture(autouse=True)
def _no_sig_required(monkeypatch):
    monkeypatch.setattr(rg.settings, "receipt_require_signature", False)
    monkeypatch.setattr(rg.settings, "progress_require_signature", False)


def test_validate_execution_receipt_accepts_utc_aware_timestamps():
    t0 = datetime.now(timezone.utc) - timedelta(seconds=2)
    t1 = datetime.now(timezone.utc) - timedelta(seconds=1)
    dur_ms = int((t1 - t0).total_seconds() * 1000)
    r = ExecutionReceipt(
        task_id="tz-task",
        agent_id="agent-1",
        step_index=1,
        tool_name="noop",
        input_hash=_hex64(),
        output_hash=_hex64(),
        started_at=t0,
        ended_at=t1,
        duration_ms=dur_ms,
        status=ToolStatus.SUCCESS,
    )
    rg.validate_execution_receipt_static(r)


def test_validate_execution_receipt_accepts_naive_utc_timestamps():
    t0 = datetime.utcnow() - timedelta(seconds=2)
    t1 = datetime.utcnow() - timedelta(seconds=1)
    dur_ms = int((t1 - t0).total_seconds() * 1000)
    r = ExecutionReceipt(
        task_id="tz-task-naive",
        agent_id="agent-1",
        step_index=1,
        tool_name="noop",
        input_hash=_hex64(),
        output_hash=_hex64(),
        started_at=t0,
        ended_at=t1,
        duration_ms=dur_ms,
        status=ToolStatus.SUCCESS,
    )
    rg.validate_execution_receipt_static(r)


def test_validate_progress_receipt_accepts_utc_aware_timestamp():
    ts = datetime.now(timezone.utc) - timedelta(seconds=1)
    p = ProgressReceipt(
        task_id="p-task",
        seller_identity_id="seller-1",
        progress_percent=10.0,
        claimed_value_percent=10.0,
        evidence_hash=_hex64(),
        runtime_log_hash=_hex64(),
        timestamp=ts,
        seller_signature="",
        validation_method="manual",
        confirmation_status=ProgressConfirmationStatus.PENDING,
    )
    rg.validate_progress_receipt_static(p)
