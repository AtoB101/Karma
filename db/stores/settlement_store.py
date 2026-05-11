"""
Karma — PostgreSQL Settlement Store
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import SettlementState, TaskStatus
from core.settlement.engine import SettlementStore
from db.models.orm import SettlementModel


class PostgresSettlementStore(SettlementStore):

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, state: SettlementState) -> None:
        existing = await self.session.get(SettlementModel, state.settlement_id)
        row_data = self._to_row(state)
        if existing:
            for k, v in row_data.items():
                setattr(existing, k, v)
        else:
            self.session.add(SettlementModel(**row_data))
        await self.session.flush()

    async def get(self, task_id: str) -> Optional[SettlementState]:
        result = await self.session.execute(
            select(SettlementModel).where(SettlementModel.task_id == task_id)
        )
        row = result.scalar_one_or_none()
        return self._from_row(row) if row else None

    async def list_by_status(self, status: TaskStatus) -> list[SettlementState]:
        result = await self.session.execute(
            select(SettlementModel).where(SettlementModel.status == status.value)
        )
        return [self._from_row(r) for r in result.scalars().all()]

    @staticmethod
    def _to_row(s: SettlementState) -> dict:
        return {
            "settlement_id":     s.settlement_id,
            "task_id":           s.task_id,
            "escrow_amount":     s.escrow_amount,
            "currency":          s.currency,
            "status":            s.status.value if hasattr(s.status, "value") else s.status,
            "client_agent_id":   s.client_agent_id,
            "worker_agent_id":   s.worker_agent_id,
            "released_amount":   s.released_amount,
            "refunded_amount":   s.refunded_amount,
            "dispute_reason":    s.dispute_reason,
            "arbitration_notes": s.arbitration_notes,
            "created_at":        s.created_at,
            "updated_at":        s.updated_at,
            "released_at":       s.released_at,
            # On-chain fields
            "settlement_mode":      getattr(s, "settlement_mode", "offchain"),
            "chain_id":             getattr(s, "chain_id", None),
            "contract_address":     getattr(s, "contract_address", None),
            "tx_hash":              getattr(s, "tx_hash", None),
            "evidence_bundle_hash": getattr(s, "evidence_bundle_hash", None),
            "onchain_status":       getattr(s, "onchain_status", None),
            "quote_id":             getattr(s, "quote_id", None),
        }

    @staticmethod
    def _from_row(row: SettlementModel) -> SettlementState:
        return SettlementState(
            settlement_id=row.settlement_id,
            task_id=row.task_id,
            escrow_amount=row.escrow_amount,
            currency=row.currency,
            status=TaskStatus(row.status),
            client_agent_id=row.client_agent_id,
            worker_agent_id=row.worker_agent_id,
            released_amount=row.released_amount,
            refunded_amount=row.refunded_amount,
            dispute_reason=row.dispute_reason,
            arbitration_notes=row.arbitration_notes,
            created_at=row.created_at,
            updated_at=row.updated_at,
            released_at=row.released_at,
            # On-chain fields
            settlement_mode=getattr(row, "settlement_mode", "offchain"),
            chain_id=getattr(row, "chain_id", None),
            contract_address=getattr(row, "contract_address", None),
            tx_hash=getattr(row, "tx_hash", None),
            evidence_bundle_hash=getattr(row, "evidence_bundle_hash", None),
            onchain_status=getattr(row, "onchain_status", None),
            quote_id=getattr(row, "quote_id", None),
        )
