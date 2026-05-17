"""Karma API — Execution Receipts"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.schemas import ExecutionReceipt
from db.session import get_db
from db.models.orm import SettlementModel, VoucherModel
from db.stores.receipt_store import PostgresReceiptStore
from services.receipt_guard import (
    _utc_aware,
    execution_receipt_signature_acceptable,
    execution_receipt_starts_before_prior_ended,
    validate_execution_receipt_static,
)
from services.receipt_templates import validate_extension_vs_task_type
from services.task_contract_guard import ensure_task_contract_exists
from services.path_param_safety import validate_public_url_segment

router = APIRouter()


@router.post("", response_model=ExecutionReceipt, status_code=201)
async def submit_receipt(receipt: ExecutionReceipt, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("task_id", receipt.task_id)
    validate_public_url_segment("receipt_id", receipt.receipt_id)
    await ensure_task_contract_exists(db, receipt.task_id)
    store = PostgresReceiptStore(db)
    try:
        validate_execution_receipt_static(receipt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if settings.receipt_template_voucher_binding:
        res = await db.execute(select(SettlementModel).where(SettlementModel.task_id == receipt.task_id))
        sm = res.scalar_one_or_none()
        if sm is not None and sm.voucher_id:
            vm = await db.get(VoucherModel, sm.voucher_id)
            task_type = vm.task_type if vm is not None else None
            try:
                validate_extension_vs_task_type(task_type=task_type, receipt=receipt)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not execution_receipt_signature_acceptable(receipt):
        raise HTTPException(status_code=400, detail="invalid receipt signature")

    latest = await store.get_latest_by_task(receipt.task_id)
    if latest is None:
        if receipt.step_index != 1:
            raise HTTPException(status_code=409, detail="first receipt step_index must be 1")
    else:
        if receipt.step_index != latest.step_index + 1:
            raise HTTPException(
                status_code=409,
                detail=f"receipt step_index must be sequential: expected {latest.step_index + 1}",
            )
        if _utc_aware(receipt.started_at) < _utc_aware(latest.started_at):
            raise HTTPException(
                status_code=409,
                detail="receipt started_at must not precede prior receipt on task",
            )
        if execution_receipt_starts_before_prior_ended(
            started_at=receipt.started_at, prior_ended_at=latest.ended_at
        ):
            raise HTTPException(status_code=409, detail="receipt timestamps out of order for task")
    try:
        await store.save(receipt)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return receipt


@router.get("/task/{task_id}", response_model=list[ExecutionReceipt])
async def list_receipts_by_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Registered before ``/{receipt_id}`` so the literal ``task`` segment is not treated as a receipt id."""
    validate_public_url_segment("task_id", task_id)
    store = PostgresReceiptStore(db)
    return await store.list_by_task(task_id)


@router.get("/{receipt_id}", response_model=ExecutionReceipt)
async def get_receipt(receipt_id: str, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("receipt_id", receipt_id)
    store = PostgresReceiptStore(db)
    receipt = await store.get(receipt_id)
    if not receipt:
        raise HTTPException(404, f"Receipt {receipt_id} not found")
    return receipt
