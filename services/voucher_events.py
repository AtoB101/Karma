"""Persist voucher lifecycle events for Console / buyer receipts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import VoucherEventModel


async def record_voucher_event(
    db: AsyncSession,
    *,
    voucher_id: str,
    event_type: str,
    payload: dict[str, Any],
    actor_identity_id: str | None = None,
    target_identity_id: str | None = None,
) -> VoucherEventModel:
    row = VoucherEventModel(
        voucher_id=voucher_id,
        event_type=event_type,
        actor_identity_id=actor_identity_id,
        target_identity_id=target_identity_id,
        payload=payload,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    return row


async def list_voucher_events(
    db: AsyncSession,
    voucher_id: str,
    *,
    for_identity_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    q = (
        select(VoucherEventModel)
        .where(VoucherEventModel.voucher_id == voucher_id)
        .order_by(VoucherEventModel.created_at.asc())
        .limit(limit)
    )
    rows = (await db.execute(q)).scalars().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        if for_identity_id:
            visible = row.actor_identity_id == for_identity_id or row.target_identity_id == for_identity_id
            if not visible and row.event_type not in (
                "voucher.created",
                "voucher.accepted",
                "voucher.rejected",
                "voucher.expired",
            ):
                continue
        out.append(
            {
                "event_id": row.event_id,
                "voucher_id": row.voucher_id,
                "event_type": row.event_type,
                "actor_identity_id": row.actor_identity_id,
                "target_identity_id": row.target_identity_id,
                "payload": row.payload,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return out
