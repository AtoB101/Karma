"""Karma API — Settlement (public state endpoints)"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import SettlementState, TaskStatus
from db.session import get_db
from db.stores.settlement_store import PostgresSettlementStore

router = APIRouter()


class CreateSettlementRequest(BaseModel):
    task_id: str
    client_agent_id: str
    escrow_amount: float
    currency: str = "USD"


class LockRequest(BaseModel):
    worker_agent_id: str


@router.post("/create", response_model=SettlementState, status_code=201)
async def create_settlement(body: CreateSettlementRequest, db: AsyncSession = Depends(get_db)):
    from datetime import datetime
    import uuid
    from config.settings import settings as _s
    state = SettlementState(
        task_id=body.task_id,
        escrow_amount=body.escrow_amount,
        currency=body.currency,
        client_agent_id=body.client_agent_id,
        status=TaskStatus.CREATED,
        settlement_mode=_s.settlement_mode,
        chain_id=_s.testnet_chain_id if _s.settlement_mode != "offchain" else None,
        contract_address=_s.karma_engine_address or None,
    )
    store = PostgresSettlementStore(db)
    await store.save(state)
    return state


@router.post("/{task_id}/lock", response_model=SettlementState)
async def lock_settlement(task_id: str, body: LockRequest, db: AsyncSession = Depends(get_db)):
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    state.status = TaskStatus.LOCKED
    state.worker_agent_id = body.worker_agent_id
    await store.save(state)
    return state


@router.post("/{task_id}/start", response_model=SettlementState)
async def start_settlement(task_id: str, db: AsyncSession = Depends(get_db)):
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    state.status = TaskStatus.RUNNING
    await store.save(state)
    return state


@router.post("/{task_id}/submit", response_model=SettlementState)
async def submit_settlement(task_id: str, db: AsyncSession = Depends(get_db)):
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    state.status = TaskStatus.SUBMITTED
    await store.save(state)
    return state


@router.post("/{task_id}/fail", response_model=SettlementState)
async def fail_settlement(task_id: str, db: AsyncSession = Depends(get_db)):
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    state.status = TaskStatus.FAILED
    await store.save(state)
    return state


@router.get("/{task_id}", response_model=SettlementState)
async def get_settlement(task_id: str, db: AsyncSession = Depends(get_db)):
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    return state
