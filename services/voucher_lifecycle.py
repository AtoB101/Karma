"""Shared voucher accept / reject transitions."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import ResponsibilityEdgeType, VoucherStatus
from db.models.orm import CapacityModel, VoucherModel
from services.capacity_ledger import assert_capacity_invariants
from core.schemas import CapacityState
from services.responsibility_graph import ingest_edge
from services.runtime_safety import audit_capacity_anchor_and_maybe_trip
from services.voucher_events import record_voucher_event
from services.openclaw_webhook import emit_openclaw_event


def _validate_capacity_row(cap: CapacityModel) -> None:
    assert_capacity_invariants(
        CapacityState(
            identity_id=cap.identity_id,
            total_locked_usdc=cap.total_locked_usdc,
            total_bill_credits=cap.total_bill_credits,
            available_credits=cap.available_credits,
            reserved_credits=cap.reserved_credits,
            in_progress_credits=cap.in_progress_credits,
            confirmed_progress_credits=cap.confirmed_progress_credits,
            disputed_credits=cap.disputed_credits,
            pending_settlement_credits=cap.pending_settlement_credits,
            burned_credits=cap.burned_credits,
            released_credits=cap.released_credits,
            updated_at=cap.updated_at,
        )
    )


async def accept_voucher_row(
    db: AsyncSession,
    row: VoucherModel,
    *,
    seller_identity_id: str,
    actor: str = "console",
) -> VoucherModel:
    if row.status != VoucherStatus.CREATED.value:
        raise HTTPException(409, f"voucher already processed: {row.status}")
    if row.expiry_time <= datetime.utcnow():
        row.status = VoucherStatus.EXPIRED.value
        raise HTTPException(409, "voucher expired")
    if row.seller_identity_id != seller_identity_id:
        raise HTTPException(403, "seller mismatch")

    cap = await db.get(CapacityModel, row.buyer_identity_id)
    if not cap or cap.available_credits < row.bill_credit_amount:
        raise HTTPException(409, "insufficient buyer available credits")

    cap.available_credits -= row.bill_credit_amount
    cap.reserved_credits += row.bill_credit_amount
    cap.updated_at = datetime.utcnow()
    _validate_capacity_row(cap)
    await audit_capacity_anchor_and_maybe_trip(db=db)

    row.status = VoucherStatus.ACCEPTED.value
    row.accepted_at = datetime.utcnow()

    await ingest_edge(
        db=db,
        source_identity_id=row.buyer_identity_id,
        target_identity_id=row.seller_identity_id,
        edge_type=ResponsibilityEdgeType.VOUCHER_ACCEPT,
        voucher_id=row.voucher_id,
        metadata={
            "amount": row.amount,
            "currency": row.currency,
            "task_type": row.task_type,
            "buyer_sub_identity_id": row.buyer_sub_identity_id,
            "seller_sub_identity_id": row.seller_sub_identity_id,
            "actor": actor,
        },
    )

    await record_voucher_event(
        db,
        voucher_id=row.voucher_id,
        event_type="voucher.accepted",
        actor_identity_id=seller_identity_id,
        target_identity_id=row.buyer_identity_id,
        payload={"actor": actor, "bill_credit_amount": float(row.bill_credit_amount)},
    )

    emit_openclaw_event(
        "voucher.accepted",
        {
            "voucher_id": row.voucher_id,
            "buyer_identity_id": row.buyer_identity_id,
            "seller_identity_id": row.seller_identity_id,
            "bill_credit_amount": float(row.bill_credit_amount),
            "amount": float(row.amount),
            "task_type": row.task_type,
        },
    )
    await db.flush()
    return row


async def reject_voucher_row(
    db: AsyncSession,
    row: VoucherModel,
    *,
    seller_identity_id: str,
    reason: str,
    actor: str = "preauth",
) -> VoucherModel:
    if row.status != VoucherStatus.CREATED.value:
        raise HTTPException(409, f"voucher already processed: {row.status}")
    if row.seller_identity_id != seller_identity_id:
        raise HTTPException(403, "seller mismatch")

    row.status = VoucherStatus.REJECTED.value
    row.rejection_reason = reason[:2000]
    row.rejected_at = datetime.utcnow()
    row.rejected_by_identity_id = seller_identity_id

    await record_voucher_event(
        db,
        voucher_id=row.voucher_id,
        event_type="voucher.rejected",
        actor_identity_id=seller_identity_id,
        target_identity_id=row.buyer_identity_id,
        payload={"reason": reason, "actor": actor, "code": actor},
    )

    emit_openclaw_event(
        "voucher.rejected",
        {
            "voucher_id": row.voucher_id,
            "buyer_identity_id": row.buyer_identity_id,
            "seller_identity_id": row.seller_identity_id,
            "reason": reason,
            "actor": actor,
        },
    )
    await db.flush()
    return row
