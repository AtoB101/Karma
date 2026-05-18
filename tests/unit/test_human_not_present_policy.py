"""Phase 3 — human-not-present policy caps."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from db.models.orm import AgentAutomationPolicyModel
from services.human_not_present_policy import (
    HNP_MAX_DAILY_LIMIT,
    HNP_MAX_SINGLE_LIMIT,
    assert_human_not_present_policy_fields,
    effective_spending_limits,
)


def test_human_not_present_requires_ack_and_auto():
    with pytest.raises(HTTPException) as exc:
        assert_human_not_present_policy_fields(
            human_not_present_allowed=True,
            auto_enabled=False,
            single_limit=10,
            daily_limit=20,
            responsibility_acknowledged=True,
        )
    assert exc.value.status_code == 400


def test_human_not_present_caps_enforced_on_upsert_fields():
    with pytest.raises(HTTPException):
        assert_human_not_present_policy_fields(
            human_not_present_allowed=True,
            auto_enabled=True,
            single_limit=HNP_MAX_SINGLE_LIMIT + 1,
            daily_limit=50,
            responsibility_acknowledged=True,
        )


def test_effective_spending_limits_tightened():
    policy = AgentAutomationPolicyModel(
        karma_identity_id="id-1",
        auto_enabled=True,
        single_limit=100,
        daily_limit=500,
        permissions=[],
        high_risk_mode="always",
        responsibility_acknowledged=True,
        human_not_present_allowed=True,
    )
    single, daily = effective_spending_limits(policy)
    assert single <= HNP_MAX_SINGLE_LIMIT
    assert daily <= HNP_MAX_DAILY_LIMIT
