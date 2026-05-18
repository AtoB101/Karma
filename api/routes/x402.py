"""Phase 2 — x402 agent HTTP payment routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.ledger_party_access import require_ledger_identity
from config.settings import settings
from db.session import get_db
from services.path_param_safety import validate_public_url_segment
from services.x402_service import pay_and_fetch_with_audit

router = APIRouter()


class X402PayAndFetchBody(BaseModel):
    task_id: str
    agent_id: str
    url: str
    max_budget_usdc: float | None = Field(default=None, gt=0)


@router.post("/pay-and-fetch")
async def x402_pay_and_fetch(
    body: X402PayAndFetchBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    x402: GET url → 402 → pay → retry → optional ExecutionReceipt with ``external_payment``.

    Requires ``X402_ENABLED=true``. Uses mock executor unless extended.
    """
    if not settings.x402_enabled:
        raise HTTPException(503, detail="x402 integration disabled")
    validate_public_url_segment("task_id", body.task_id)
    validate_public_url_segment("agent_id", body.agent_id)
    require_ledger_identity(request, body.agent_id)
    cap = body.max_budget_usdc or settings.x402_default_max_budget_usdc
    if cap > settings.x402_hard_max_budget_usdc:
        raise HTTPException(400, detail="max_budget_usdc exceeds platform hard cap")
    try:
        out = await pay_and_fetch_with_audit(
            db,
            task_id=body.task_id,
            agent_id=body.agent_id,
            url=body.url,
            max_budget_usdc=cap,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    await db.commit()
    return out
