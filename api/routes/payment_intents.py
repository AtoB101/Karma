"""Payment Intent API — POST/GET /v1/payment-intents (Phase 3)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import CreatePaymentIntentRequest, PaymentIntent
from db.session import get_db
from services.path_param_safety import validate_public_url_segment
from services.payment_intent_service import (
    bind_payment_intent,
    create_payment_intent,
    get_payment_intent,
)
from services.trade_pipeline_security import require_idempotency_key_if_configured

router = APIRouter()


def _to_schema(data: dict) -> PaymentIntent:
    return PaymentIntent.model_validate(
        {
            "intentId": data["intentId"],
            "merchantRef": data["merchantRef"],
            "status": data["status"],
            "createdAt": data["createdAt"],
            "updatedAt": data["updatedAt"],
            "payer": data["payer"],
            "payee": data["payee"],
            "token": data["token"],
            "amount": data["amount"],
            "chainId": data["chainId"],
            "policyId": data["policyId"],
            "expiresAt": data["expiresAt"],
            "taskId": data.get("taskId"),
            "voucherId": data.get("voucherId"),
        }
    )


@router.post("", response_model=PaymentIntent, status_code=201)
async def create_payment_intent_route(
    body: CreatePaymentIntentRequest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency_key_if_configured(idempotency_key)
    expires = body.expires_at
    if expires.tzinfo:
        expires = expires.replace(tzinfo=None)
    row, replay = await create_payment_intent(
        db,
        merchant_ref=body.merchant_ref,
        payer=body.payer,
        payee=body.payee,
        token=body.token,
        amount=body.amount,
        chain_id=body.chain_id,
        policy_id=body.policy_id,
        expires_at=expires,
        idempotency_key=key,
        task_id=body.task_id,
        voucher_id=body.voucher_id,
    )
    await db.commit()
    from services.payment_intent_service import _row_to_api

    out = _to_schema(_row_to_api(row))
    if replay:
        return out
    return out


@router.get("/{intent_id}", response_model=PaymentIntent)
async def get_payment_intent_route(intent_id: str, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("intent_id", intent_id)
    from services.payment_intent_service import _row_to_api

    row = await get_payment_intent(db, intent_id)
    if not row:
        raise HTTPException(status_code=404, detail="PAYMENT_INTENT_NOT_FOUND")
    return _to_schema(_row_to_api(row))


class BindPaymentIntentBody(BaseModel):
    taskId: str | None = Field(default=None, alias="taskId")
    voucherId: str | None = Field(default=None, alias="voucherId")

    model_config = {"populate_by_name": True}


@router.post("/{intent_id}/bind", response_model=PaymentIntent)
async def bind_payment_intent_route(
    intent_id: str,
    body: BindPaymentIntentBody,
    db: AsyncSession = Depends(get_db),
):
    validate_public_url_segment("intent_id", intent_id)
    if not body.taskId and not body.voucherId:
        raise HTTPException(status_code=400, detail="taskId or voucherId required")
    row = await bind_payment_intent(
        db,
        intent_id,
        task_id=body.taskId,
        voucher_id=body.voucherId,
    )
    await db.commit()
    from services.payment_intent_service import _row_to_api

    return _to_schema(_row_to_api(row))
