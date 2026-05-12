"""Karma API — Responsibility graph path hash and risk signals."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import (
    ExplainableRiskReport,
    ResponsibilityBatchScanResult,
    ResponsibilityBatchScanRun,
    ResponsibilityDeadLetterPurgeResult,
    ResponsibilityDeadLetterRequeueBatchResult,
    ResponsibilityDeadLetterSweepResult,
    ResponsibilityEdgeIngestResult,
    ResponsibilityEdgeType,
    ResponsibilityQueueMaintenanceTickResult,
    ResponsibilityRecoverStaleRunsResult,
    ResponsibilityScanExecutionMode,
    ResponsibilityScanOpsReport,
    ResponsibilityScanQueueStats,
    ResponsibilityScanRunEvent,
    ResponsibilityWorkerPullExecuteResult,
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
    cancel_scan_run,
    claim_next_scan_run,
    execute_scan_run,
    export_explainable_risk_report,
    get_batch_scan_result,
    get_identity_path_features,
    get_identity_score,
    get_identity_signals,
    get_public_risk_model,
    get_scan_run_ops_report,
    get_scan_run_queue_stats,
    get_task_path_summary,
    get_task_temporal_consistency_report,
    heartbeat_scan_run,
    ingest_edge,
    list_scan_run_events,
    list_dead_letter_scan_runs,
    purge_dead_letter_scan_runs,
    pull_and_execute_scan_run,
    recover_stale_scan_runs,
    requeue_dead_letter_scan_run,
    requeue_dead_letter_scan_runs,
    run_scan_queue_maintenance_tick,
    sweep_dead_letter_scan_runs,
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
    execution_mode: ResponsibilityScanExecutionMode = ResponsibilityScanExecutionMode.SYNC
    scan_mode: ResponsibilityScanMode = ResponsibilityScanMode.FULL
    base_scan_id: str | None = None
    window_hours: int = Field(default=24, ge=1, le=24 * 30)
    max_hops: int = Field(default=4, ge=1, le=12)
    min_score_threshold: float = Field(default=8.0, ge=0.0, le=100.0)
    retry_max_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff_seconds: int = Field(default=30, ge=1, le=3600)


class ExecuteScanRunRequest(BaseModel):
    force: bool = False
    runner_identity_id: str | None = None
    lease_seconds: int = Field(default=300, ge=1, le=3600)


class ClaimScanRunRequest(BaseModel):
    runner_identity_id: str
    lease_seconds: int = Field(default=300, ge=1, le=3600)
    include_failed: bool = True


class HeartbeatScanRunRequest(BaseModel):
    runner_identity_id: str
    lease_seconds: int = Field(default=300, ge=1, le=3600)


class CancelScanRunRequest(BaseModel):
    runner_identity_id: str | None = None
    reason: str | None = None


class RecoverStaleScanRunsRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=1000)


class SweepDeadLetterScanRunsRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=1000)
    reason: str | None = None


class RequeueDeadLetterScanRunsRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=1000)
    reason: str | None = None


class PurgeDeadLetterScanRunsRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=1000)
    older_than_hours: int = Field(default=72, ge=1, le=24 * 365)


class RequeueScanRunRequest(BaseModel):
    reason: str | None = None


class PullExecuteScanRunRequest(BaseModel):
    runner_identity_id: str
    lease_seconds: int = Field(default=300, ge=1, le=3600)
    include_failed: bool = True
    force_execute: bool = False


class ScanQueueMaintenanceTickRequest(BaseModel):
    runner_identity_id: str
    recover_limit: int = Field(default=100, ge=1, le=1000)
    max_claim_execute: int = Field(default=5, ge=0, le=100)
    lease_seconds: int = Field(default=300, ge=1, le=3600)
    include_failed: bool = True


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
            execution_mode=body.execution_mode,
            scan_mode=body.scan_mode,
            base_scan_id=body.base_scan_id,
            window_hours=body.window_hours,
            max_hops=body.max_hops,
            min_score_threshold=body.min_score_threshold,
            retry_max_attempts=body.retry_max_attempts,
            retry_backoff_seconds=body.retry_backoff_seconds,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/scan-runs/claim", response_model=ResponsibilityBatchScanRun)
async def claim_scan_run(
    body: ClaimScanRunRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await claim_next_scan_run(
        db=db,
        runner_identity_id=body.runner_identity_id,
        lease_seconds=body.lease_seconds,
        include_failed=body.include_failed,
    )
    if not result:
        raise HTTPException(404, "no claimable scan run available")
    return result


@router.get("/scan-runs/queue/stats", response_model=ResponsibilityScanQueueStats)
async def get_scan_queue_stats(db: AsyncSession = Depends(get_db)):
    return await get_scan_run_queue_stats(db=db)


@router.get("/scan-runs/ops/report", response_model=ResponsibilityScanOpsReport)
async def get_scan_ops_report(
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    recent_events_limit: int = Query(default=50, ge=1, le=1000),
    top_failure_limit: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await get_scan_run_ops_report(
        db=db,
        window_hours=window_hours,
        recent_events_limit=recent_events_limit,
        top_failure_limit=top_failure_limit,
    )


@router.post("/scan-runs/recover-stale", response_model=ResponsibilityRecoverStaleRunsResult)
async def recover_stale_runs(
    body: RecoverStaleScanRunsRequest,
    db: AsyncSession = Depends(get_db),
):
    return await recover_stale_scan_runs(db=db, limit=body.limit)


@router.get("/scan-runs/dead-letter", response_model=list[ResponsibilityBatchScanRun])
async def list_dead_letter_runs(
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    return await list_dead_letter_scan_runs(db=db, limit=limit)


@router.post("/scan-runs/dead-letter/sweep", response_model=ResponsibilityDeadLetterSweepResult)
async def sweep_dead_letter_runs(
    body: SweepDeadLetterScanRunsRequest,
    db: AsyncSession = Depends(get_db),
):
    return await sweep_dead_letter_scan_runs(
        db=db,
        limit=body.limit,
        reason=body.reason,
    )


@router.post("/scan-runs/dead-letter/requeue-batch", response_model=ResponsibilityDeadLetterRequeueBatchResult)
async def requeue_dead_letter_batch(
    body: RequeueDeadLetterScanRunsRequest,
    db: AsyncSession = Depends(get_db),
):
    return await requeue_dead_letter_scan_runs(
        db=db,
        limit=body.limit,
        reason=body.reason,
    )


@router.post("/scan-runs/dead-letter/purge", response_model=ResponsibilityDeadLetterPurgeResult)
async def purge_dead_letter_runs(
    body: PurgeDeadLetterScanRunsRequest,
    db: AsyncSession = Depends(get_db),
):
    return await purge_dead_letter_scan_runs(
        db=db,
        limit=body.limit,
        older_than_hours=body.older_than_hours,
    )


@router.post("/scan-runs/worker/pull-execute", response_model=ResponsibilityWorkerPullExecuteResult)
async def pull_execute_scan_run(
    body: PullExecuteScanRunRequest,
    db: AsyncSession = Depends(get_db),
):
    return await pull_and_execute_scan_run(
        db=db,
        runner_identity_id=body.runner_identity_id,
        lease_seconds=body.lease_seconds,
        include_failed=body.include_failed,
        force_execute=body.force_execute,
    )


@router.post("/scan-runs/maintenance/tick", response_model=ResponsibilityQueueMaintenanceTickResult)
async def maintenance_tick(
    body: ScanQueueMaintenanceTickRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_scan_queue_maintenance_tick(
        db=db,
        runner_identity_id=body.runner_identity_id,
        recover_limit=body.recover_limit,
        max_claim_execute=body.max_claim_execute,
        lease_seconds=body.lease_seconds,
        include_failed=body.include_failed,
    )


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


@router.get("/scan-runs/{scan_id}/events", response_model=list[ResponsibilityScanRunEvent])
async def get_scan_run_events(
    scan_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await list_scan_run_events(db=db, scan_id=scan_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/scan-runs/{scan_id}/requeue", response_model=ResponsibilityBatchScanRun)
async def requeue_scan_run(
    scan_id: str,
    body: RequeueScanRunRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await requeue_dead_letter_scan_run(
            db=db,
            scan_id=scan_id,
            reason=body.reason,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(404, message) from exc
        raise HTTPException(409, message) from exc


@router.post("/scan-runs/{scan_id}/execute", response_model=ResponsibilityBatchScanResult)
async def execute_scan(
    scan_id: str,
    body: ExecuteScanRunRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await execute_scan_run(
            db=db,
            scan_id=scan_id,
            runner_identity_id=body.runner_identity_id,
            lease_seconds=body.lease_seconds,
            force=body.force,
            require_failed=False,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(404, message) from exc
        raise HTTPException(409, message) from exc


@router.post("/scan-runs/{scan_id}/heartbeat", response_model=ResponsibilityBatchScanRun)
async def heartbeat_scan(
    scan_id: str,
    body: HeartbeatScanRunRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await heartbeat_scan_run(
            db=db,
            scan_id=scan_id,
            runner_identity_id=body.runner_identity_id,
            lease_seconds=body.lease_seconds,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(404, message) from exc
        raise HTTPException(409, message) from exc


@router.post("/scan-runs/{scan_id}/retry", response_model=ResponsibilityBatchScanResult)
async def retry_scan(scan_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await execute_scan_run(
            db=db,
            scan_id=scan_id,
            force=False,
            require_failed=True,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(404, message) from exc
        raise HTTPException(409, message) from exc


@router.post("/scan-runs/{scan_id}/cancel", response_model=ResponsibilityBatchScanRun)
async def cancel_scan(
    scan_id: str,
    body: CancelScanRunRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await cancel_scan_run(
            db=db,
            scan_id=scan_id,
            runner_identity_id=body.runner_identity_id,
            reason=body.reason,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(404, message) from exc
        raise HTTPException(409, message) from exc


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

