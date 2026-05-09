"""
Karma — PostgreSQL Receipt Store
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.hooks.hook_layer import ReceiptStore
from core.schemas import ExecutionReceipt, ToolStatus
from db.models.orm import ReceiptModel


class PostgresReceiptStore(ReceiptStore):

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, receipt: ExecutionReceipt) -> None:
        existing = await self.session.get(ReceiptModel, receipt.receipt_id)
        if existing:
            for field, value in self._to_row(receipt).items():
                setattr(existing, field, value)
        else:
            self.session.add(ReceiptModel(**self._to_row(receipt)))
        await self.session.flush()

    async def get(self, receipt_id: str) -> Optional[ExecutionReceipt]:
        row = await self.session.get(ReceiptModel, receipt_id)
        return self._from_row(row) if row else None

    async def list_by_task(self, task_id: str) -> list[ExecutionReceipt]:
        result = await self.session.execute(
            select(ReceiptModel)
            .where(ReceiptModel.task_id == task_id)
            .order_by(ReceiptModel.step_index)
        )
        return [self._from_row(r) for r in result.scalars().all()]

    @staticmethod
    def _to_row(r: ExecutionReceipt) -> dict:
        return {
            "receipt_id":    r.receipt_id,
            "task_id":       r.task_id,
            "agent_id":      r.agent_id,
            "step_index":    r.step_index,
            "tool_name":     r.tool_name,
            "input_hash":    r.input_hash,
            "output_hash":   r.output_hash,
            "started_at":    r.started_at,
            "ended_at":      r.ended_at,
            "duration_ms":   r.duration_ms,
            "status":        r.status.value if hasattr(r.status, "value") else r.status,
            "error_message": r.error_message,
            "metadata_":     r.metadata,
            "signature":     r.signature,
        }

    @staticmethod
    def _from_row(row: ReceiptModel) -> ExecutionReceipt:
        return ExecutionReceipt(
            receipt_id=row.receipt_id,
            task_id=row.task_id,
            agent_id=row.agent_id,
            step_index=row.step_index,
            tool_name=row.tool_name,
            input_hash=row.input_hash,
            output_hash=row.output_hash,
            started_at=row.started_at,
            ended_at=row.ended_at,
            duration_ms=row.duration_ms,
            status=ToolStatus(row.status),
            error_message=row.error_message,
            metadata=row.metadata_ or {},
            signature=row.signature,
        )
