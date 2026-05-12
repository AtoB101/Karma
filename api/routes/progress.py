"""Karma API — Progress receipts."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import ProgressConfirmationStatus, ProgressReceipt, TaskStatus
from core.settlement.engine import can_transition
from db.models.orm import ProgressReceiptModel
from db.session import get_db
from db.stores.settlement_store import PostgresSettlementStore

router = APIRouter()


@router.post("", response_model=ProgressReceipt, status_code=201)
async def submit_progress_receipt(progress: ProgressReceipt, db: AsyncSession = Depends(get_db)):
    existing = await db.get(ProgressReceiptModel, progress.progress_receipt_id)
    if existing:
        raise HTTPException(409, f"Progress receipt {progress.progress_receipt_id} already exists")

    settlement_store = PostgresSettlementStore(db)
    settlement = await settlement_store.get(progress.task_id)
    if not settlement:
        raise HTTPException(404, f"Settlement for task {progress.task_id} not found")
    if not can_transition(settlement.status, TaskStatus.PROGRESS_SUBMITTED):
        raise HTTPException(409, f"invalid status transition: {settlement.status.value} -> progress_submitted")

    db.add(
        ProgressReceiptModel(
            progress_receipt_id=progress.progress_receipt_id,
            task_id=progress.task_id,
            seller_identity_id=progress.seller_identity_id,
            progress_percent=progress.progress_percent,
            claimed_value_percent=progress.claimed_value_percent,
            evidence_hash=progress.evidence_hash,
            runtime_log_hash=progress.runtime_log_hash,
            timestamp=progress.timestamp,
            seller_signature=progress.seller_signature,
            validation_method=progress.validation_method,
            confirmation_status=progress.confirmation_status.value,
            confirmed_at=progress.confirmed_at,
        )
    )
    settlement.status = TaskStatus.PROGRESS_SUBMITTED
    await settlement_store.save(settlement)
    return progress


@router.post("/{progress_receipt_id}/confirm", response_model=ProgressReceipt)
async def confirm_progress_receipt(progress_receipt_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(ProgressReceiptModel, progress_receipt_id)
    if not row:
        raise HTTPException(404, f"Progress receipt {progress_receipt_id} not found")
    if row.confirmation_status == ProgressConfirmationStatus.CONFIRMED.value:
        return _to_schema(row)

    settlement_store = PostgresSettlementStore(db)
    settlement = await settlement_store.get(row.task_id)
    if not settlement:
        raise HTTPException(404, f"Settlement for task {row.task_id} not found")
    if not can_transition(settlement.status, TaskStatus.PROGRESS_CONFIRMED):
        raise HTTPException(409, f"invalid status transition: {settlement.status.value} -> progress_confirmed")

    row.confirmation_status = ProgressConfirmationStatus.CONFIRMED.value
    row.confirmed_at = datetime.utcnow()
    settlement.status = TaskStatus.PROGRESS_CONFIRMED
    await settlement_store.save(settlement)
    await db.flush()
    return _to_schema(row)


@router.get("/task/{task_id}", response_model=list[ProgressReceipt])
async def list_progress_receipts(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ProgressReceiptModel)
        .where(ProgressReceiptModel.task_id == task_id)
        .order_by(ProgressReceiptModel.timestamp.asc())
    )
    rows = result.scalars().all()
    return [_to_schema(row) for row in rows]


def _to_schema(row: ProgressReceiptModel) -> ProgressReceipt:
    return ProgressReceipt(
        progress_receipt_id=row.progress_receipt_id,
        task_id=row.task_id,
        seller_identity_id=row.seller_identity_id,
        progress_percent=row.progress_percent,
        claimed_value_percent=row.claimed_value_percent,
        evidence_hash=row.evidence_hash,
        runtime_log_hash=row.runtime_log_hash,
        timestamp=row.timestamp,
        seller_signature=row.seller_signature,
        validation_method=row.validation_method,
        confirmation_status=ProgressConfirmationStatus(row.confirmation_status),
        confirmed_at=row.confirmed_at,
    )

