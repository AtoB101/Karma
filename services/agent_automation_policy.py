"""Persisted operator policy — fund limits and Runtime permissions before AI automation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import AgentAutomationPolicyModel
from services.human_not_present_policy import assert_human_not_present_policy_fields
from services.runtime_key_service import ALLOWED_PERMISSIONS, normalize_permissions

HIGH_RISK_MODES = frozenset({"always", "above_single", "off"})


def policy_to_dict(row: AgentAutomationPolicyModel) -> dict[str, Any]:
    return {
        "karma_identity_id": row.karma_identity_id,
        "auto_enabled": bool(row.auto_enabled),
        "single_limit": float(row.single_limit),
        "daily_limit": float(row.daily_limit),
        "permissions": list(row.permissions or []),
        "high_risk_mode": row.high_risk_mode,
        "responsibility_acknowledged": bool(row.responsibility_acknowledged),
        "policy_version": int(row.policy_version),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by_actor": row.updated_by_actor,
        "preauth_enabled": bool(getattr(row, "preauth_enabled", False)),
        "allowed_task_types": list(getattr(row, "allowed_task_types", None) or []),
        "task_precision_min": getattr(row, "task_precision_min", None),
        "task_precision_max": getattr(row, "task_precision_max", None),
        "trusted_counterparty_ids": list(getattr(row, "trusted_counterparty_ids", None) or []),
        "payment_code_ttl_seconds": int(getattr(row, "payment_code_ttl_seconds", 3600) or 3600),
        "responsibility_boundary_id": getattr(row, "responsibility_boundary_id", None),
        "auto_accept_incoming": bool(getattr(row, "auto_accept_incoming", False)),
        "auto_execute_pipeline": bool(getattr(row, "auto_execute_pipeline", False)),
        "human_not_present_allowed": bool(getattr(row, "human_not_present_allowed", False)),
    }


async def get_automation_policy(
    db: AsyncSession,
    karma_identity_id: str,
) -> AgentAutomationPolicyModel | None:
    return await db.get(AgentAutomationPolicyModel, karma_identity_id)


async def upsert_automation_policy(
    db: AsyncSession,
    *,
    karma_identity_id: str,
    auto_enabled: bool,
    single_limit: float,
    daily_limit: float,
    permissions: list[str],
    high_risk_mode: str,
    responsibility_acknowledged: bool,
    updated_by_actor: str | None = None,
    preauth_enabled: bool = False,
    allowed_task_types: list[str] | None = None,
    task_precision_min: float | None = None,
    task_precision_max: float | None = None,
    trusted_counterparty_ids: list[str] | None = None,
    payment_code_ttl_seconds: int = 3600,
    responsibility_boundary_id: str | None = None,
    auto_accept_incoming: bool = False,
    auto_execute_pipeline: bool = False,
    human_not_present_allowed: bool = False,
) -> AgentAutomationPolicyModel:
    assert_human_not_present_policy_fields(
        human_not_present_allowed=human_not_present_allowed,
        auto_enabled=auto_enabled,
        single_limit=single_limit,
        daily_limit=daily_limit,
        responsibility_acknowledged=responsibility_acknowledged,
    )
    if single_limit <= 0 or daily_limit <= 0:
        raise HTTPException(status_code=400, detail="single_limit and daily_limit must be > 0")
    if daily_limit + 1e-9 < single_limit:
        raise HTTPException(status_code=400, detail="daily_limit must be >= single_limit")
    if high_risk_mode not in HIGH_RISK_MODES:
        raise HTTPException(status_code=400, detail=f"high_risk_mode must be one of {sorted(HIGH_RISK_MODES)}")
    if (auto_enabled or preauth_enabled) and not responsibility_acknowledged:
        raise HTTPException(
            status_code=400,
            detail="responsibility_acknowledged must be true before enabling AI automation or preauth",
        )
    if task_precision_min is not None and task_precision_max is not None:
        if task_precision_max + 1e-9 < task_precision_min:
            raise HTTPException(status_code=400, detail="task_precision_max must be >= task_precision_min")
    if payment_code_ttl_seconds < 60:
        raise HTTPException(status_code=400, detail="payment_code_ttl_seconds must be >= 60")
    if auto_enabled:
        perms = normalize_permissions(permissions)
    else:
        perms = sorted({p.strip() for p in permissions if (p or "").strip()})
        for p in perms:
            if p not in ALLOWED_PERMISSIONS:
                raise HTTPException(status_code=400, detail=f"unknown or disallowed permission: {p}")

    row = await db.get(AgentAutomationPolicyModel, karma_identity_id)
    if row:
        row.auto_enabled = auto_enabled
        row.single_limit = single_limit
        row.daily_limit = daily_limit
        row.permissions = perms
        row.high_risk_mode = high_risk_mode
        row.responsibility_acknowledged = responsibility_acknowledged
        row.preauth_enabled = preauth_enabled
        row.allowed_task_types = list(allowed_task_types or [])
        row.task_precision_min = task_precision_min
        row.task_precision_max = task_precision_max
        row.trusted_counterparty_ids = list(trusted_counterparty_ids or [])
        row.payment_code_ttl_seconds = int(payment_code_ttl_seconds)
        row.responsibility_boundary_id = responsibility_boundary_id
        row.auto_accept_incoming = auto_accept_incoming
        row.auto_execute_pipeline = auto_execute_pipeline
        row.human_not_present_allowed = human_not_present_allowed
        row.policy_version = int(row.policy_version) + 1
        row.updated_at = datetime.utcnow()
        row.updated_by_actor = updated_by_actor
    else:
        row = AgentAutomationPolicyModel(
            karma_identity_id=karma_identity_id,
            auto_enabled=auto_enabled,
            single_limit=single_limit,
            daily_limit=daily_limit,
            permissions=perms,
            high_risk_mode=high_risk_mode,
            responsibility_acknowledged=responsibility_acknowledged,
            preauth_enabled=preauth_enabled,
            allowed_task_types=list(allowed_task_types or []),
            task_precision_min=task_precision_min,
            task_precision_max=task_precision_max,
            trusted_counterparty_ids=list(trusted_counterparty_ids or []),
            payment_code_ttl_seconds=int(payment_code_ttl_seconds),
            responsibility_boundary_id=responsibility_boundary_id,
            auto_accept_incoming=auto_accept_incoming,
            auto_execute_pipeline=auto_execute_pipeline,
            human_not_present_allowed=human_not_present_allowed,
            policy_version=1,
            updated_at=datetime.utcnow(),
            updated_by_actor=updated_by_actor,
        )
        db.add(row)
    await db.flush()
    return row


def assert_runtime_key_matches_policy(
    *,
    policy: AgentAutomationPolicyModel,
    permissions: list[str],
    single_limit: float,
    daily_limit: float,
) -> None:
    """Runtime Key mint must not exceed saved operator policy."""
    if not policy.auto_enabled:
        raise HTTPException(
            status_code=403,
            detail="AI automation disabled — save automation policy with auto_enabled=true first",
        )
    if not policy.responsibility_acknowledged:
        raise HTTPException(
            status_code=403,
            detail="responsibility boundary not acknowledged in automation policy",
        )
    saved_perms = sorted(policy.permissions or [])
    req_perms = sorted(normalize_permissions(permissions))
    if req_perms != saved_perms:
        raise HTTPException(
            status_code=403,
            detail="runtime key permissions must match saved automation policy",
        )
    if single_limit > policy.single_limit + 1e-9:
        raise HTTPException(status_code=403, detail="single_limit exceeds saved automation policy")
    if daily_limit > policy.daily_limit + 1e-9:
        raise HTTPException(status_code=403, detail="daily_limit exceeds saved automation policy")


def policy_summary_for_console(policy: AgentAutomationPolicyModel | None) -> dict[str, Any]:
    if not policy:
        return {
            "configured": False,
            "auto_enabled": False,
            "allowed_permissions": sorted(ALLOWED_PERMISSIONS),
        }
    return {
        "configured": True,
        "auto_enabled": policy.auto_enabled,
        "single_limit": policy.single_limit,
        "daily_limit": policy.daily_limit,
        "permissions": list(policy.permissions or []),
        "high_risk_mode": policy.high_risk_mode,
        "responsibility_acknowledged": policy.responsibility_acknowledged,
        "policy_version": policy.policy_version,
        "preauth_enabled": bool(getattr(policy, "preauth_enabled", False)),
        "auto_accept_incoming": bool(getattr(policy, "auto_accept_incoming", False)),
    }
