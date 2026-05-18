"""Payment Intent API — create, query, bind, lifecycle (Phase 3)."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import PaymentIntentModel

INTENT_STATUSES = frozenset({"created", "authorized", "settled", "cancelled", "expired"})


def _intent_id() -> str:
    return f"pi_{secrets.token_hex(12)}"


def _row_to_api(row: PaymentIntentModel) -> dict[str, Any]:
    return {
        "intentId": row.intent_id,
        "merchantRef": row.merchant_ref,
        "status": row.status,
        "createdAt": row.created_at.isoformat() + "Z" if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() + "Z" if row.updated_at else None,
        "payer": row.payer,
        "payee": row.payee,
        "token": row.token,
        "amount": row.amount,
        "chainId": row.chain_id,
        "policyId": row.policy_id,
        "expiresAt": row.expires_at.isoformat() + "Z" if row.expires_at else None,
        "taskId": row.task_id,
        "voucherId": row.voucher_id,
    }


async def get_payment_intent(db: AsyncSession, intent_id: str) -> PaymentIntentModel | None:
    return await db.get(PaymentIntentModel, intent_id)


async def create_payment_intent(
    db: AsyncSession,
    *,
    merchant_ref: str,
    payer: str,
    payee: str,
    token: str,
    amount: str,
    chain_id: int,
    policy_id: str,
    expires_at: datetime,
    idempotency_key: str,
    task_id: str | None = None,
    voucher_id: str | None = None,
) -> tuple[PaymentIntentModel, bool]:
    """Create intent; returns (row, idempotent_replay)."""
    if not amount.isdigit():
        raise HTTPException(status_code=400, detail="amount must be numeric string")
    existing = await db.execute(
        select(PaymentIntentModel).where(PaymentIntentModel.idempotency_key == idempotency_key)
    )
    replay = existing.scalar_one_or_none()
    if replay:
        return replay, True

    now = datetime.utcnow()
    if expires_at <= now:
        raise HTTPException(status_code=400, detail="expiresAt must be in the future")

    row = PaymentIntentModel(
        intent_id=_intent_id(),
        merchant_ref=merchant_ref,
        idempotency_key=idempotency_key,
        status="created",
        payer=payer,
        payee=payee,
        token=token,
        amount=str(amount),
        chain_id=int(chain_id),
        policy_id=policy_id,
        expires_at=expires_at,
        task_id=task_id,
        voucher_id=voucher_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    if task_id or voucher_id:
        row.status = "authorized"
        row.updated_at = datetime.utcnow()
    return row, False


async def bind_payment_intent(
    db: AsyncSession,
    intent_id: str,
    *,
    task_id: str | None = None,
    voucher_id: str | None = None,
) -> PaymentIntentModel:
    row = await get_payment_intent(db, intent_id)
    if not row:
        raise HTTPException(status_code=404, detail="PAYMENT_INTENT_NOT_FOUND")
    if row.status in ("settled", "cancelled", "expired"):
        raise HTTPException(status_code=409, detail=f"cannot bind intent in status {row.status}")
    if task_id:
        row.task_id = task_id
    if voucher_id:
        row.voucher_id = voucher_id
    if row.task_id or row.voucher_id:
        row.status = "authorized"
    row.updated_at = datetime.utcnow()
    await db.flush()
    return row


async def mark_intents_settled_for_task(db: AsyncSession, task_id: str) -> int:
    """Mark all authorized/created intents linked to task_id as settled."""
    res = await db.execute(
        select(PaymentIntentModel).where(
            PaymentIntentModel.task_id == task_id,
            PaymentIntentModel.status.in_(("created", "authorized")),
        )
    )
    count = 0
    now = datetime.utcnow()
    for row in res.scalars():
        row.status = "settled"
        row.updated_at = now
        count += 1
    if count:
        await db.flush()
    return count


async def expire_stale_intents(db: AsyncSession) -> int:
    now = datetime.utcnow()
    res = await db.execute(
        select(PaymentIntentModel).where(
            PaymentIntentModel.status.in_(("created", "authorized")),
            PaymentIntentModel.expires_at < now,
        )
    )
    n = 0
    for row in res.scalars():
        row.status = "expired"
        row.updated_at = now
        n += 1
    if n:
        await db.flush()
    return n
