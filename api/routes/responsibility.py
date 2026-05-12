"""Karma API — Responsibility graph path hash and risk signals."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import (
    ExplainableRiskReport,
    ResponsibilityBatchScanResult,
    ResponsibilityEdgeIngestResult,
    ResponsibilityEdgeType,
    ResponsibilityPathFeaturesSummary,
    ResponsibilityPublicRiskModel,
    ResponsibilityRiskSignal,
    ResponsibilityScanMode,
    ResponsibilityScoreSummary,
    TaskTemporalConsistencyReport,
    TaskPathHashSummary,
)
from db.session import get_db
from services.responsibility_graph import (
    export_explainable_risk_report,
    get_batch_scan_result,
    get_identity_path_features,
    get_identity_score,
    get_identity_signals,
    get_public_risk_model,
    get_task_path_summary,
    get_task_temporal_consistency_report,
    ingest_edge,
    run_batch_scan,
)

router = APIRouter()


class IngestResponsibilityEdgeRequest(BaseModel):
    source_identity_id: str
    target_identity_id: str
    edge_type: ResponsibilityEdgeType = ResponsibilityEdgeType.MANUAL_LINK
    task_id: str | None = None
    voucher_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CreateBatchScanRunRequest(BaseModel):
    identity_ids: list[str] | None = None
    scan_mode: ResponsibilityScanMode = ResponsibilityScanMode.FULL
    base_scan_id: str | None = None
    window_hours: int = Field(default=24, ge=1, le=24 * 30)
    max_hops: int = Field(default=4, ge=1, le=12)
    min_score_threshold: float = Field(default=8.0, ge=0.0, le=100.0)


class ExportExplainableRiskReportRequest(BaseModel):
    identity_id: str | None = None
    task_id: str | None = None
    signer_identity_id: str | None = None
    signature: str | None = None
    window_hours: int = Field(default=24, ge=1, le=24 * 30)
    max_hops: int = Field(default=4, ge=1, le=12)
    top_signals_limit: int = Field(default=20, ge=1, le=200)


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


@router.get("/identity/{identity_id}/path-features", response_model=ResponsibilityPathFeaturesSummary)
async def get_identity_path_feature_summary(
    identity_id: str,
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    max_hops: int = Query(default=4, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
):
    return await get_identity_path_features(
        db=db,
        identity_id=identity_id,
        window_hours=window_hours,
        max_hops=max_hops,
    )


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


@router.get("/task/{task_id}/temporal-consistency", response_model=TaskTemporalConsistencyReport)
async def get_task_temporal_consistency(task_id: str, db: AsyncSession = Depends(get_db)):
    return await get_task_temporal_consistency_report(db=db, task_id=task_id)


@router.get("/model/public-risk", response_model=ResponsibilityPublicRiskModel)
async def get_public_model():
    return get_public_risk_model()


@router.post("/scan-runs", response_model=ResponsibilityBatchScanResult, status_code=201)
async def create_batch_scan_run(
    body: CreateBatchScanRunRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await run_batch_scan(
            db=db,
            identity_ids=body.identity_ids,
            scan_mode=body.scan_mode,
            base_scan_id=body.base_scan_id,
            window_hours=body.window_hours,
            max_hops=body.max_hops,
            min_score_threshold=body.min_score_threshold,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/scan-runs/{scan_id}", response_model=ResponsibilityBatchScanResult)
async def get_scan_run(
    scan_id: str,
    findings_limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    result = await get_batch_scan_result(db=db, scan_id=scan_id, findings_limit=findings_limit)
    if not result:
        raise HTTPException(404, f"scan run {scan_id} not found")
    return result


@router.post("/reports/export", response_model=ExplainableRiskReport)
async def export_report(
    body: ExportExplainableRiskReportRequest,
    db: AsyncSession = Depends(get_db),
):
    if bool(body.identity_id) == bool(body.task_id):
        raise HTTPException(400, "exactly one of identity_id or task_id must be provided")
    return await export_explainable_risk_report(
        db=db,
        identity_id=body.identity_id,
        task_id=body.task_id,
        window_hours=body.window_hours,
        max_hops=body.max_hops,
        top_signals_limit=body.top_signals_limit,
        signer_identity_id=body.signer_identity_id,
        signature=body.signature,
    )

