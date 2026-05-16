"""OpenClaw operator helpers — handoff draft, readiness, attestation, events."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import get_current_agent_id
from db.session import get_db
from services.openclaw_automation_readiness import Role, evaluate_automation_readiness
from services.openclaw_handoff_attestation import (
    confirm_handoff_attestation,
    get_handoff_attestation,
)
from services.openclaw_handoff_draft import build_handoff_draft
from services.openclaw_webhook import list_stored_events

router = APIRouter()


class HandoffConfirmBody(BaseModel):
    task_id: str = Field(min_length=1)
    karma_identity_id: str = Field(min_length=1)
    role: str = Field(default="buyer", pattern="^(buyer|seller)$")
    trace_id: str = ""
    handoff: dict[str, Any] | None = None


@router.get("/handoff-events")
async def get_handoff_events(
    task_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    _actor: str = Depends(get_current_agent_id),
):
    """
    Return recent OpenClaw handoff events stored in-process when OPENCLAW_WEBHOOK_STORE_EVENTS=true.

    For production multi-instance deployments, configure OPENCLAW_WEBHOOK_URL to your Claw receiver instead.
    """
    return {"events": list_stored_events(task_id=task_id, limit=limit)}


@router.get("/handoff-draft")
async def get_handoff_draft(
    task_id: str = Query(..., min_length=1),
    trace_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(get_current_agent_id),
):
    """
    Suggest OpenClaw handoff v1 JSON from ledger state (read-only).

    Operators must review ``manual_console_steps_completed`` before passing the handoff to Claw MCP.
    Voucher create/accept and Runtime Key mint remain Console-only.
    """
    return await build_handoff_draft(db, task_id=task_id.strip(), trace_id=trace_id)


@router.get("/automation-readiness")
async def get_automation_readiness(
    task_id: str = Query(..., min_length=1),
    role: str = Query(default="buyer", pattern="^(buyer|seller)$"),
    karma_identity_id: str | None = Query(default=None),
    for_handoff_confirm: bool = Query(
        default=False,
        description="When true, omit attestation requirement (step before POST handoff-confirm).",
    ),
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(get_current_agent_id),
):
    """
    Server-verified checklist before task-scoped AI automation.

    Use ``for_handoff_confirm=true`` before ``POST /handoff-confirm``; full automation requires attestation when enabled.
    """
    return await evaluate_automation_readiness(
        db,
        task_id=task_id.strip(),
        role=role,  # type: ignore[arg-type]
        karma_identity_id=karma_identity_id,
        require_attestation=not for_handoff_confirm,
    )


@router.get("/handoff-attestation")
async def get_handoff_attestation_route(
    task_id: str = Query(..., min_length=1),
    karma_identity_id: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(get_current_agent_id),
):
    """Return whether Console registered handoff attestation for this task + identity."""
    row = await get_handoff_attestation(
        db, task_id=task_id.strip(), karma_identity_id=karma_identity_id.strip()
    )
    if not row:
        return {
            "attested": False,
            "task_id": task_id,
            "karma_identity_id": karma_identity_id,
        }
    return {
        "attested": True,
        "attestation_id": row.attestation_id,
        "task_id": row.task_id,
        "karma_identity_id": row.karma_identity_id,
        "handoff_hash": row.handoff_hash,
        "policy_version": row.policy_version,
        "trace_id": row.trace_id,
        "created_at": row.created_at.isoformat(),
    }


@router.post("/handoff-confirm")
async def post_handoff_confirm(
    body: HandoffConfirmBody,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(get_current_agent_id),
):
    """
    Operator confirms Console authorization is complete; persists server attestation.

    Requires ``ready_for_task_automation`` from automation-readiness first.
    """
    out = await confirm_handoff_attestation(
        db,
        task_id=body.task_id.strip(),
        karma_identity_id=body.karma_identity_id.strip(),
        role=body.role,  # type: ignore[arg-type]
        trace_id=body.trace_id,
        handoff=body.handoff,
        attested_by_actor=actor,
    )
    await db.commit()
    return out
