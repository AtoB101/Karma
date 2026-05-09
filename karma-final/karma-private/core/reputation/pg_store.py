"""
PRIVATE — PostgreSQL Reputation Store
Full persistence for reputation records including private fields.
DO NOT commit to public repository.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from core.reputation.system import ReputationStore, _ReputationRecord
from core.schemas import AgentRole


class PostgresReputationStore(ReputationStore):

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, record: _ReputationRecord) -> None:
        from db.models.orm import ReputationModel
        existing = await self.session.get(ReputationModel, record.agent_id)
        row_data = {
            "agent_id":             record.agent_id,
            "role":                 record.role.value if hasattr(record.role, "value") else record.role,
            "score":                record.score,
            "total_tasks":          record.total_tasks,
            "successful_tasks":     record.successful_tasks,
            "disputed_tasks":       record.disputed_tasks,
            "arbitration_wins":     record.arbitration_wins,
            "arbitration_losses":   record.arbitration_losses,
            "consecutive_successes":record.consecutive_successes,
            "wash_trade_flags":     record.wash_trade_flags,
            "last_updated":         record.last_updated,
        }
        if existing:
            for k, v in row_data.items():
                setattr(existing, k, v)
        else:
            from db.models.orm import ReputationModel
            self.session.add(ReputationModel(**row_data))
        await self.session.flush()

    async def get(self, agent_id: str) -> Optional[_ReputationRecord]:
        from db.models.orm import ReputationModel
        row = await self.session.get(ReputationModel, agent_id)
        if not row:
            return None
        return self._from_row(row)

    async def top_n(self, n: int) -> list[_ReputationRecord]:
        from db.models.orm import ReputationModel
        result = await self.session.execute(
            select(ReputationModel).order_by(desc(ReputationModel.score)).limit(n)
        )
        return [self._from_row(r) for r in result.scalars().all()]

    @staticmethod
    def _from_row(row) -> _ReputationRecord:
        record = _ReputationRecord(
            agent_id=row.agent_id,
            role=AgentRole(row.role),
        )
        record.score               = row.score
        record.total_tasks         = row.total_tasks
        record.successful_tasks    = row.successful_tasks
        record.disputed_tasks      = row.disputed_tasks
        record.arbitration_wins    = row.arbitration_wins
        record.arbitration_losses  = row.arbitration_losses
        record.consecutive_successes = row.consecutive_successes
        record.wash_trade_flags    = row.wash_trade_flags
        record.last_updated        = row.last_updated
        return record
