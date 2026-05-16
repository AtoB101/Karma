"""OpenClaw operator helpers — poll handoff events and export handoff drafts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import get_current_agent_id
from db.session import get_db
from services.openclaw_handoff_draft import build_handoff_draft
from services.openclaw_webhook import list_stored_events

router = APIRouter()


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
