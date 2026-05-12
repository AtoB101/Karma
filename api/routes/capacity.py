"""Karma API — Identity capacity ledger (USDC 1:1 anchored)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import CapacityState
from db.models.orm import CapacityModel
from db.session import get_db
from services.capacity_ledger import assert_capacity_invariants

router = APIRouter()


class AmountRequest(BaseModel):
    amount: float = Field(gt=0.0)


@router.get("/{identity_id}", response_model=CapacityState)
async def get_capacity(identity_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(CapacityModel, identity_id)
    if not row:
        return CapacityState(identity_id=identity_id)
    return _to_schema(row)


@router.post("/{identity_id}/lock", response_model=CapacityState)
async def lock_usdc(identity_id: str, body: AmountRequest, db: AsyncSession = Depends(get_db)):
    row = await db.get(CapacityModel, identity_id)
    if not row:
        row = CapacityModel(
            identity_id=identity_id,
            total_locked_usdc=0.0,
            total_bill_credits=0.0,
            available_credits=0.0,
            reserved_credits=0.0,
            in_progress_credits=0.0,
            confirmed_progress_credits=0.0,
            disputed_credits=0.0,
            pending_settlement_credits=0.0,
            burned_credits=0.0,
            released_credits=0.0,
            updated_at=datetime.utcnow(),
        )
        db.add(row)
    row.total_locked_usdc += body.amount
    row.total_bill_credits += body.amount
    row.available_credits += body.amount
    row.updated_at = datetime.utcnow()

    state = _to_schema(row)
    _validate(state)
    await db.flush()
    return state


@router.post("/{identity_id}/release", response_model=CapacityState)
async def release_unused(identity_id: str, body: AmountRequest, db: AsyncSession = Depends(get_db)):
    row = await db.get(CapacityModel, identity_id)
    if not row:
        raise HTTPException(404, f"Capacity for {identity_id} not found")
    if row.available_credits < body.amount:
        raise HTTPException(409, "insufficient available credits")

    row.available_credits -= body.amount
    row.total_bill_credits -= body.amount
    row.total_locked_usdc -= body.amount
    row.released_credits += body.amount
    row.updated_at = datetime.utcnow()

    state = _to_schema(row)
    _validate(state)
    await db.flush()
    return state


def _to_schema(row: CapacityModel) -> CapacityState:
    return CapacityState(
        identity_id=row.identity_id,
        total_locked_usdc=row.total_locked_usdc,
        total_bill_credits=row.total_bill_credits,
        available_credits=row.available_credits,
        reserved_credits=row.reserved_credits,
        in_progress_credits=row.in_progress_credits,
        confirmed_progress_credits=row.confirmed_progress_credits,
        disputed_credits=row.disputed_credits,
        pending_settlement_credits=row.pending_settlement_credits,
        burned_credits=row.burned_credits,
        released_credits=row.released_credits,
        updated_at=row.updated_at,
    )


def _validate(state: CapacityState) -> None:
    try:
        assert_capacity_invariants(state)
    except ValueError as exc:
        raise HTTPException(500, "capacity invariant check failed") from exc

