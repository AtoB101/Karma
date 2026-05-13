"""Karma API — Task Contracts"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.schemas import TaskContract
from db.session import get_db
from db.models.orm import CapacityModel, TaskContractModel
from services.signing import sha256_of

router = APIRouter()


class CreateContractRequest(BaseModel):
    client_agent_id: str
    title: str
    description: str
    expected_output_schema: dict
    expected_step_count: int
    escrow_amount: float
    currency: str = "USD"
    deadline_at: datetime


@router.post("", response_model=TaskContract, status_code=201)
async def create_contract(
    body: CreateContractRequest,
    db: AsyncSession = Depends(get_db),
):
    if body.escrow_amount < settings.escrow_min_amount - 1e-9:
        raise HTTPException(
            status_code=400,
            detail=f"escrow_amount must be >= {settings.escrow_min_amount}",
        )
    if body.escrow_amount > settings.escrow_max_amount + 1e-9:
        raise HTTPException(
            status_code=400,
            detail=f"escrow_amount must be <= {settings.escrow_max_amount}",
        )
    cap = await db.get(CapacityModel, body.client_agent_id)
    if cap is not None and float(cap.available_credits) + 1e-9 < float(body.escrow_amount):
        raise HTTPException(
            status_code=409,
            detail="escrow_amount exceeds buyer available_credits on capacity ledger",
        )

    contract = TaskContract(**body.model_dump())
    contract.contract_hash = sha256_of(contract.model_dump(exclude={"contract_hash"}))

    db.add(TaskContractModel(
        task_id=contract.task_id,
        client_agent_id=contract.client_agent_id,
        title=contract.title,
        description=contract.description,
        expected_output_schema=contract.expected_output_schema,
        expected_step_count=contract.expected_step_count,
        escrow_amount=contract.escrow_amount,
        currency=contract.currency,
        deadline_at=contract.deadline_at,
        contract_hash=contract.contract_hash,
        created_at=contract.created_at,
    ))
    return contract


@router.get("/{task_id}", response_model=TaskContract)
async def get_contract(task_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(TaskContractModel, task_id)
    if not row:
        raise HTTPException(404, f"Contract {task_id} not found")
    return _row_to_contract(row)


@router.patch("/{task_id}/assign")
async def assign_worker(
    task_id: str,
    worker_agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(TaskContractModel, task_id)
    if not row:
        raise HTTPException(404)
    row.worker_agent_id = worker_agent_id
    return _row_to_contract(row)


def _row_to_contract(row: TaskContractModel) -> TaskContract:
    return TaskContract(
        task_id=row.task_id,
        client_agent_id=row.client_agent_id,
        worker_agent_id=row.worker_agent_id,
        title=row.title,
        description=row.description,
        expected_output_schema=row.expected_output_schema,
        expected_step_count=row.expected_step_count,
        escrow_amount=row.escrow_amount,
        currency=row.currency,
        deadline_at=row.deadline_at,
        contract_hash=row.contract_hash,
        created_at=row.created_at,
    )
