"""Karma API — Execution Receipts"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import ExecutionReceipt
from db.session import get_db
from db.stores.receipt_store import PostgresReceiptStore
from services.receipt_guard import (
    validate_execution_receipt_static,
    verify_execution_receipt_signature,
)

router = APIRouter()


@router.get("/{receipt_id}", response_model=ExecutionReceipt)
async def get_receipt(receipt_id: str, db: AsyncSession = Depends(get_db)):
    store = PostgresReceiptStore(db)
    receipt = await store.get(receipt_id)
    if not receipt:
        raise HTTPException(404, f"Receipt {receipt_id} not found")
    return receipt


@router.get("/task/{task_id}", response_model=list[ExecutionReceipt])
async def list_receipts_by_task(task_id: str, db: AsyncSession = Depends(get_db)):
    store = PostgresReceiptStore(db)
    return await store.list_by_task(task_id)


@router.post("", response_model=ExecutionReceipt, status_code=201)
async def submit_receipt(receipt: ExecutionReceipt, db: AsyncSession = Depends(get_db)):
    store = PostgresReceiptStore(db)
    try:
        validate_execution_receipt_static(receipt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not verify_execution_receipt_signature(receipt):
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
        if receipt.started_at < latest.ended_at:
            raise HTTPException(status_code=409, detail="receipt timestamps out of order for task")
    try:
        await store.save(receipt)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return receipt
