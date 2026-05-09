"""Karma API — Reputation (public read endpoints)"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import AgentRole, ReputationSnapshot
from db.session import get_db
from db.models.orm import ReputationModel

router = APIRouter()


@router.get("/{agent_id}", response_model=ReputationSnapshot)
async def get_reputation(agent_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(ReputationModel, agent_id)
    if not row:
        raise HTTPException(404, f"No reputation record for agent {agent_id}")
    return _from_row(row)


@router.get("", response_model=list[ReputationSnapshot])
async def leaderboard(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ReputationModel).order_by(desc(ReputationModel.score)).limit(limit)
    )
    return [_from_row(r) for r in result.scalars().all()]


def _from_row(row: ReputationModel) -> ReputationSnapshot:
    success_rate = (
        row.successful_tasks / row.total_tasks if row.total_tasks > 0 else 0.0
    )
    return ReputationSnapshot(
        agent_id=row.agent_id,
        role=AgentRole(row.role),
        score=row.score,
        total_tasks=row.total_tasks,
        successful_tasks=row.successful_tasks,
        disputed_tasks=row.disputed_tasks,
        success_rate=success_rate,
        last_updated=row.last_updated,
    )
