"""Runtime safety-mode guardrails and capacity anchor audits."""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import RuntimeSafetyModeState
from db.models.orm import CapacityModel

ANCHOR_EPSILON = 1e-9
DEFAULT_ANCHOR_BREACH_REASON = "capacity anchor breach: total bill credits exceed total locked usdc"

_STATE = RuntimeSafetyModeState()


def get_runtime_safety_mode_state() -> RuntimeSafetyModeState:
    return _STATE.model_copy()


def set_runtime_safety_mode(
    *,
    enabled: bool,
    reason: str | None = None,
    actor_id: str | None = None,
) -> RuntimeSafetyModeState:
    global _STATE
    now = datetime.utcnow()
    if enabled:
        _STATE = _STATE.model_copy(
            update={
                "enabled": True,
                "reason": reason or _STATE.reason or "manual safety mode enabled",
                "triggered_by": actor_id or "system",
                "triggered_at": _STATE.triggered_at or now,
            }
        )
    else:
        _STATE = _STATE.model_copy(
            update={
                "enabled": False,
                "reason": reason or "safety mode disabled",
                "triggered_by": actor_id or "system",
                "triggered_at": now,
            }
        )
    return _STATE.model_copy()


def assert_runtime_operation_allowed(operation: str) -> None:
    if not _STATE.enabled:
        return
    raise HTTPException(
        status_code=503,
        detail=f"safety mode active: blocked operation '{operation}'",
    )


async def audit_capacity_anchor_and_maybe_trip(
    db: AsyncSession,
    *,
    actor_id: str | None = "system",
) -> RuntimeSafetyModeState:
    result = await db.execute(
        select(
            func.coalesce(func.sum(CapacityModel.total_locked_usdc), 0.0),
            func.coalesce(func.sum(CapacityModel.total_bill_credits), 0.0),
        )
    )
    total_locked_usdc, total_bill_credits = result.one()
    now = datetime.utcnow()

    global _STATE
    _STATE = _STATE.model_copy(
        update={
            "last_anchor_audit_at": now,
            "total_locked_usdc": float(total_locked_usdc or 0.0),
            "total_bill_credits": float(total_bill_credits or 0.0),
        }
    )

    if _STATE.total_bill_credits > _STATE.total_locked_usdc + ANCHOR_EPSILON:
        set_runtime_safety_mode(
            enabled=True,
            reason=DEFAULT_ANCHOR_BREACH_REASON,
            actor_id=actor_id,
        )
        raise HTTPException(status_code=503, detail="safety mode enabled: capacity anchor breach detected")

    return _STATE.model_copy()
