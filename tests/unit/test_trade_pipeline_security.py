"""Trade pipeline launch guards."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from config.settings import settings
from services.trade_pipeline_security import (
    clamp_spec_to_policies,
    normalize_idempotency_key,
    validate_chain_anchor_for_mode,
    validate_launch_parties,
)


def test_validate_launch_parties_rejects_same_id():
    with pytest.raises(HTTPException) as exc:
        validate_launch_parties(buyer_identity_id="a", seller_identity_id="a")
    assert exc.value.status_code == 400


def test_idempotency_key_length():
    with pytest.raises(HTTPException):
        normalize_idempotency_key("short")
    assert normalize_idempotency_key("a" * 16) == "a" * 16


def test_chain_anchor_required_on_testnet(monkeypatch):
    monkeypatch.setattr(settings, "settlement_mode", "testnet")
    with pytest.raises(HTTPException) as exc:
        validate_chain_anchor_for_mode(None)
    assert "chain_anchor_hash" in str(exc.value.detail)

    ok = validate_chain_anchor_for_mode("0x" + "ab" * 32)
    assert ok.startswith("0x")


def test_clamp_spec_respects_single_limit():
    from db.models.orm import AgentAutomationPolicyModel

    buyer = AgentAutomationPolicyModel(
        karma_identity_id="b",
        auto_enabled=True,
        single_limit=5.0,
        daily_limit=100.0,
        permissions=[],
        high_risk_mode="always",
        allowed_task_types=["api.caption"],
        task_precision_min=0.5,
        task_precision_max=5.0,
    )
    seller = AgentAutomationPolicyModel(
        karma_identity_id="s",
        auto_enabled=True,
        single_limit=100.0,
        daily_limit=500.0,
        permissions=[],
        high_risk_mode="always",
    )
    spec = {
        "amount": 50.0,
        "bill_credit_amount": 50.0,
        "task_precision": 1.0,
        "task_type": "api.caption",
    }
    with pytest.raises(HTTPException):
        clamp_spec_to_policies(spec, buyer_policy=buyer, seller_policy=seller)
