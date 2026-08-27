"""Trade order pipeline — buyer requirement → auto order → accept → execute."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import TradeOrderModel
from db.session import get_db
from services.ledger_party_access import require_ledger_identity
from services.path_param_safety import validate_public_url_segment
from services.trade_launch_signing import (
    build_signing_preview,
    sign_trade_launch_with_configured_backend,
)
from services.trade_order_pipeline import launch_preauth_trade_order
from services.trade_pipeline_security import require_idempotency_key_if_configured

router = APIRouter()


class TradeLaunchBodyBase(BaseModel):
    buyer_identity_id: str
    seller_identity_id: str
    requirement_text: str = Field(min_length=1, max_length=32000)
    amount: float | None = Field(default=None, gt=0)
    task_precision: float | None = Field(default=None, ge=0)
    task_type: str | None = None
    chain_anchor_hash: str | None = None


class LaunchTradeOrderRequest(TradeLaunchBodyBase):
    buyer_signature: str = Field(default="0xtrade_pipeline_buyer_sig")
    # Deadline the buyer signed (returned by /orders/launch/signing-preview).
    # Optional; bounded to now+TTL server-side. Required for reproducible EIP-712
    # verification when more than a second elapses between preview and launch.
    deadline_unix: int | None = Field(default=None, gt=0)


class LaunchFromIntentRequest(BaseModel):
    """Discover a seller from requirement text, then launch the trade pipeline."""
    buyer_identity_id: str
    requirement_text: str = Field(min_length=1, max_length=32000)
    seller_identity_id: str | None = None  # optional override; else auto-discover
    amount: float | None = Field(default=None, gt=0)
    task_precision: float | None = Field(default=None, ge=0)
    task_type: str | None = None
    chain_anchor_hash: str | None = None
    buyer_signature: str = Field(default="0xtrade_pipeline_buyer_sig")
    discovery_limit: int = Field(default=5, ge=1, le=20)


@router.post("/orders/launch-from-intent", status_code=201)
async def launch_trade_order_from_intent(
    body: LaunchFromIntentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """
    Assistant-friendly path: user states a goal → discover Karma merchant/agent → launch trade.

    If ``seller_identity_id`` is omitted, ranks local agents / DID projections / A2A registry
    via the same matcher as ``POST /v1/discovery/intent``.
    """
    from api.routes.discovery import DiscoverIntentRequest, discover_for_intent

    validate_public_url_segment("buyer_identity_id", body.buyer_identity_id)
    require_ledger_identity(request, body.buyer_identity_id)
    normalized_key = require_idempotency_key_if_configured(idempotency_key)

    seller_id = body.seller_identity_id
    discovery_plan = None
    if not seller_id:
        discovery_plan = await discover_for_intent(
            DiscoverIntentRequest(
                requirement_text=body.requirement_text,
                buyer_identity_id=body.buyer_identity_id,
                amount=body.amount,
                limit=body.discovery_limit,
            ),
            db,
        )
        recommended = discovery_plan.get("recommended")
        if not recommended:
            raise HTTPException(
                404,
                "no matching agent/merchant found for this intent; register merchants with "
                "matching capabilities or pass seller_identity_id",
            )
        seller_id = recommended["agent_id"]

    validate_public_url_segment("seller_identity_id", seller_id)
    result = await launch_preauth_trade_order(
        db,
        buyer_identity_id=body.buyer_identity_id,
        seller_identity_id=seller_id,
        requirement_text=body.requirement_text,
        buyer_signature=body.buyer_signature,
        amount=body.amount,
        task_precision=body.task_precision,
        task_type=body.task_type,
        chain_anchor_hash=body.chain_anchor_hash,
        launch_idempotency_key=normalized_key,
    )
    await db.commit()
    result = dict(result)
    result["discovered_seller_identity_id"] = seller_id
    if discovery_plan is not None:
        result["discovery"] = {
            "intent": discovery_plan.get("intent"),
            "recommended": discovery_plan.get("recommended"),
            "candidates": discovery_plan.get("candidates"),
        }
    if result.get("idempotent_replay"):
        return result
    return result


@router.post("/orders/launch", status_code=201)
async def launch_trade_order(
    body: LaunchTradeOrderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """
    Launch full preauth pipeline when both parties saved automation-policy with
    preauth_enabled, auto_enabled, auto_execute_pipeline, and an active Runtime Key.

    Send ``Idempotency-Key`` (8–256 chars) for safe retries; required when ``APP_ENV=production``.
    """
    validate_public_url_segment("buyer_identity_id", body.buyer_identity_id)
    validate_public_url_segment("seller_identity_id", body.seller_identity_id)
    require_ledger_identity(request, body.buyer_identity_id)
    normalized_key = require_idempotency_key_if_configured(idempotency_key)

    result = await launch_preauth_trade_order(
        db,
        buyer_identity_id=body.buyer_identity_id,
        seller_identity_id=body.seller_identity_id,
        requirement_text=body.requirement_text,
        buyer_signature=body.buyer_signature,
        amount=body.amount,
        task_precision=body.task_precision,
        task_type=body.task_type,
        chain_anchor_hash=body.chain_anchor_hash,
        launch_idempotency_key=normalized_key,
        deadline_unix=body.deadline_unix,
    )
    await db.commit()
    if result.get("idempotent_replay"):
        return result
    return result


@router.post("/orders/launch/signing-preview")
async def trade_launch_signing_preview(
    body: TradeLaunchBodyBase,
    request: Request,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Return EIP-712 typed data for wallet signing (Open Wallet / Phase 1)."""
    validate_public_url_segment("buyer_identity_id", body.buyer_identity_id)
    validate_public_url_segment("seller_identity_id", body.seller_identity_id)
    require_ledger_identity(request, body.buyer_identity_id)
    normalized_key = require_idempotency_key_if_configured(idempotency_key)
    return await build_signing_preview(
        db,
        buyer_identity_id=body.buyer_identity_id,
        seller_identity_id=body.seller_identity_id,
        requirement_text=body.requirement_text,
        amount=body.amount,
        task_type=body.task_type,
        task_precision=body.task_precision,
        launch_idempotency_key=normalized_key,
        chain_anchor_hash=body.chain_anchor_hash,
    )


@router.post("/orders/launch/sign-with-backend")
async def trade_launch_sign_with_backend(
    body: TradeLaunchBodyBase,
    request: Request,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Sign launch intent server-side when ``KARMA_SIGNING_BACKEND`` is ``local`` or ``env`` (dev/CI)."""
    validate_public_url_segment("buyer_identity_id", body.buyer_identity_id)
    validate_public_url_segment("seller_identity_id", body.seller_identity_id)
    require_ledger_identity(request, body.buyer_identity_id)
    normalized_key = require_idempotency_key_if_configured(idempotency_key)
    result = await sign_trade_launch_with_configured_backend(
        db,
        buyer_identity_id=body.buyer_identity_id,
        seller_identity_id=body.seller_identity_id,
        requirement_text=body.requirement_text,
        amount=body.amount,
        task_type=body.task_type,
        task_precision=body.task_precision,
        launch_idempotency_key=normalized_key,
        chain_anchor_hash=body.chain_anchor_hash,
    )
    await db.commit()
    return result


@router.get("/orders/{order_id}")
async def get_trade_order(order_id: str, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("order_id", order_id)
    row = await db.get(TradeOrderModel, order_id)
    if not row:
        raise HTTPException(404, "order not found")
    return {
        "order_id": row.order_id,
        "task_id": row.task_id,
        "voucher_id": row.voucher_id,
        "buyer_identity_id": row.buyer_identity_id,
        "seller_identity_id": row.seller_identity_id,
        "status": row.status,
        "status_detail": row.status_detail,
        "decomposed_spec": row.decomposed_spec,
        "pipeline_version": row.pipeline_version,
        "launch_idempotency_key": row.launch_idempotency_key,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
