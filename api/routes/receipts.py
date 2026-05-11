"""Karma API — Execution Receipts"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import ExecutionReceipt
from db.session import get_db
from db.stores.receipt_store import PostgresReceiptStore

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
    await store.save(receipt)
    return receipt
