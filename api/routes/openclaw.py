"""OpenClaw operator helpers — poll recent handoff events (dev / single worker)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.middleware.auth import get_current_agent_id
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
