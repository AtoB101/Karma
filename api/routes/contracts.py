"""Karma API — Task Contracts"""
from __future__ import annotations

from datetime import datetime
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.schemas import TaskContract
from db.session import get_db
from db.models.orm import CapacityModel, TaskContractModel
from services.path_param_safety import validate_public_url_segment
from services.signing import sha256_of

router = APIRouter()


class CreateContractRequest(BaseModel):
    task_id: str | None = Field(
        default=None,
        description="Optional explicit task id (must be unused). If omitted, a UUID is assigned.",
    )
    client_agent_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(default="", max_length=32768)
    expected_output_schema: dict
    expected_step_count: int = Field(ge=1, le=1_000_000)
    escrow_amount: float
    currency: str = Field(default="USD", max_length=16)
    deadline_at: datetime

    @model_validator(mode="after")
    def _limit_schema_json_size(self) -> "CreateContractRequest":
        raw = json.dumps(self.expected_output_schema, sort_keys=True, default=str)
        if len(raw.encode("utf-8")) > 65536:
            raise ValueError("expected_output_schema JSON must be <= 65536 bytes")
        return self


@router.post("", response_model=TaskContract, status_code=201)
async def create_contract(
    body: CreateContractRequest,
    db: AsyncSession = Depends(get_db),
):
    if body.task_id is not None:
        validate_public_url_segment("task_id", body.task_id)
        if await db.get(TaskContractModel, body.task_id):
            raise HTTPException(409, "task_id already in use")

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

    data = body.model_dump()
    if body.task_id is not None:
        data["task_id"] = body.task_id
    else:
        data.pop("task_id", None)
    contract = TaskContract(**data)
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
    validate_public_url_segment("task_id", task_id)
    validate_public_url_segment("worker_agent_id", worker_agent_id)
    row = await db.get(TaskContractModel, task_id)
    if not row:
        raise HTTPException(404)
    if worker_agent_id == row.client_agent_id:
        raise HTTPException(
            status_code=409,
            detail="worker_agent_id cannot equal contract client_agent_id (self-assignment)",
        )
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
