"""Karma API — Responsibility graph path hash and risk signals."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import (
    ResponsibilityEdgeIngestResult,
    ResponsibilityEdgeType,
    ResponsibilityPublicRiskModel,
    ResponsibilityRiskSignal,
    ResponsibilityScoreSummary,
    TaskPathHashSummary,
)
from db.session import get_db
from services.responsibility_graph import (
    get_identity_score,
    get_identity_signals,
    get_public_risk_model,
    get_task_path_summary,
    ingest_edge,
)

router = APIRouter()


class IngestResponsibilityEdgeRequest(BaseModel):
    source_identity_id: str
    target_identity_id: str
    edge_type: ResponsibilityEdgeType = ResponsibilityEdgeType.MANUAL_LINK
    task_id: str | None = None
    voucher_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


@router.post("/edges", response_model=ResponsibilityEdgeIngestResult, status_code=201)
async def ingest_responsibility_edge(
    body: IngestResponsibilityEdgeRequest,
    db: AsyncSession = Depends(get_db),
):
    if not body.source_identity_id.strip() or not body.target_identity_id.strip():
        raise HTTPException(400, "source_identity_id and target_identity_id are required")
    result = await ingest_edge(
        db=db,
        source_identity_id=body.source_identity_id,
        target_identity_id=body.target_identity_id,
        edge_type=body.edge_type,
        task_id=body.task_id,
        voucher_id=body.voucher_id,
        metadata=body.metadata,
    )
    return result


@router.get("/identity/{identity_id}/signals", response_model=list[ResponsibilityRiskSignal])
async def list_identity_signals(
    identity_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await get_identity_signals(db=db, identity_id=identity_id, limit=limit)


@router.get("/identity/{identity_id}/score", response_model=ResponsibilityScoreSummary)
async def get_identity_risk_score(
    identity_id: str,
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
):
    return await get_identity_score(
        db=db,
        identity_id=identity_id,
        window_hours=window_hours,
    )


@router.get("/task/{task_id}/path-hash", response_model=TaskPathHashSummary)
async def get_task_path_hash(task_id: str, db: AsyncSession = Depends(get_db)):
    return await get_task_path_summary(db=db, task_id=task_id)


@router.get("/model/public-risk", response_model=ResponsibilityPublicRiskModel)
async def get_public_model():
    return get_public_risk_model()

