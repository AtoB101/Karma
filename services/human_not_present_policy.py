"""Human-not-present automation bounds (Phase 3)."""

from __future__ import annotations

from fastapi import HTTPException

from db.models.orm import AgentAutomationPolicyModel

# Stricter caps when operator enables unattended (human-not-present) automation.
HNP_MAX_SINGLE_LIMIT = 50.0
HNP_MAX_DAILY_LIMIT = 200.0
HNP_SPEND_MULTIPLIER = 0.5


def assert_human_not_present_policy_fields(
    *,
    human_not_present_allowed: bool,
    auto_enabled: bool,
    single_limit: float,
    daily_limit: float,
    responsibility_acknowledged: bool,
) -> None:
    if not human_not_present_allowed:
        return
    if not responsibility_acknowledged:
        raise HTTPException(
            status_code=400,
            detail="responsibility_acknowledged required for human_not_present_allowed",
        )
    if not auto_enabled:
        raise HTTPException(
            status_code=400,
            detail="auto_enabled must be true when human_not_present_allowed is set",
        )
    if single_limit > HNP_MAX_SINGLE_LIMIT + 1e-9:
        raise HTTPException(
            status_code=400,
            detail=f"human_not_present single_limit must be <= {HNP_MAX_SINGLE_LIMIT}",
        )
    if daily_limit > HNP_MAX_DAILY_LIMIT + 1e-9:
        raise HTTPException(
            status_code=400,
            detail=f"human_not_present daily_limit must be <= {HNP_MAX_DAILY_LIMIT}",
        )


def effective_spending_limits(policy: AgentAutomationPolicyModel) -> tuple[float, float]:
    """Return (single, daily) limits after human-not-present tightening."""
    single = float(policy.single_limit)
    daily = float(policy.daily_limit)
    if bool(getattr(policy, "human_not_present_allowed", False)):
        single = min(single, HNP_MAX_SINGLE_LIMIT) * HNP_SPEND_MULTIPLIER
        daily = min(daily, HNP_MAX_DAILY_LIMIT) * HNP_SPEND_MULTIPLIER
    return single, daily
