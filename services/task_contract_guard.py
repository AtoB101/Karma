"""Task contract existence checks (settlement / receipts)."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import TaskContractModel


async def ensure_task_contract_exists(db: AsyncSession, task_id: str) -> TaskContractModel:
    row = await db.get(TaskContractModel, task_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="task contract not found for this task_id",
        )
    return row
