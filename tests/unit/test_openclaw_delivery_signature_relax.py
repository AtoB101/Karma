"""OpenClaw local Phase 1 — relaxed delivery signatures when trade EIP-712 is off."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from config.settings import settings
from core.schemas import ExecutionReceipt, ProgressReceipt, ToolStatus
from services import receipt_guard as rg


def _execution_receipt(*, signature: str | None = "0xopenclaw_execution_dev") -> ExecutionReceipt:
    now = datetime.now(timezone.utc)
    return ExecutionReceipt(
        receipt_id="rcpt-relax-1",
        task_id="task-relax-1",
        agent_id="seller-demo",
        step_index=1,
        tool_name="openclaw.test",
        input_hash="a" * 64,
        output_hash="b" * 64,
        started_at=now,
        ended_at=now,
        duration_ms=1,
        status=ToolStatus.SUCCESS,
        signature=signature,
    )


def _progress(*, seller_signature: str = "0xopenclaw_progress_dev") -> ProgressReceipt:
    return ProgressReceipt(
        task_id="task-relax-1",
        seller_identity_id="seller-demo",
        progress_percent=10.0,
        claimed_value_percent=5.0,
        evidence_hash="c" * 64,
        runtime_log_hash="d" * 64,
        timestamp=datetime.now(timezone.utc),
        seller_signature=seller_signature,
        validation_method="openclaw_test",
    )


@pytest.fixture
def local_phase1_env(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "trade_launch_require_eip712", False)
    monkeypatch.setattr(settings, "openclaw_local_phase1_auto_relax", True)
    monkeypatch.setattr(settings, "openclaw_relax_delivery_signatures", None)
    monkeypatch.setattr(settings, "receipt_require_signature", True)
    monkeypatch.setattr(settings, "progress_require_signature", True)
    monkeypatch.setattr(settings, "receipt_strict_recent_timestamps", False)


def test_delivery_relaxed_auto_when_local_phase1_flag(local_phase1_env):
    assert rg.delivery_signatures_relaxed() is True
    rg.validate_execution_receipt_static(_execution_receipt(signature=None))
    rg.validate_progress_receipt_static(_progress(seller_signature=""))
    assert rg.execution_receipt_signature_acceptable(_execution_receipt(signature=None)) is True


def test_delivery_not_relaxed_when_trade_eip712_on(local_phase1_env, monkeypatch):
    monkeypatch.setattr(settings, "trade_launch_require_eip712", True)
    assert rg.delivery_signatures_relaxed() is False


def test_delivery_not_relaxed_without_auto_flag(local_phase1_env, monkeypatch):
    monkeypatch.setattr(settings, "openclaw_local_phase1_auto_relax", False)
    assert rg.delivery_signatures_relaxed() is False
    with pytest.raises(ValueError, match="receipt signature is required"):
        rg.validate_execution_receipt_static(_execution_receipt(signature=None))


def test_delivery_explicit_override_false(local_phase1_env, monkeypatch):
    monkeypatch.setattr(settings, "openclaw_relax_delivery_signatures", False)
    assert rg.delivery_signatures_relaxed() is False


def test_delivery_never_relaxed_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "trade_launch_require_eip712", False)
    monkeypatch.setattr(settings, "openclaw_relax_delivery_signatures", True)
    assert rg.delivery_signatures_relaxed() is False

