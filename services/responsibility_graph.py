"""Responsibility graph ingestion and public-safe risk signal detection."""
from __future__ import annotations

import hashlib
import json
from collections import deque
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import (
    ExplainableRiskReport,
    ExplainableRiskReportTarget,
    ReportSignaturePlaceholder,
    ReportSignatureStatus,
    ResponsibilityBatchScanResult,
    ResponsibilityBatchScanRun,
    ResponsibilityEdge,
    ResponsibilityEdgeIngestResult,
    ResponsibilityEdgeType,
    ResponsibilityPathFeaturesSummary,
    ResponsibilityRiskSignal,
    ResponsibilityScanFinding,
    ResponsibilityScanExecutionMode,
    ResponsibilityScanMode,
    ResponsibilityScanRunStatus,
    ResponsibilitySignalSeverity,
    ResponsibilitySignalType,
    ResponsibilityScoreBand,
    ResponsibilityScoreSummary,
    ResponsibilityPublicRiskModel,
    TaskTemporalConsistencyReport,
    TemporalConsistencyIssue,
    TemporalConsistencyIssueType,
    TaskPathHashSummary,
)
from db.models.orm import (
    ResponsibilityEdgeModel,
    ResponsibilityScanFindingModel,
    ResponsibilityScanRunModel,
    ResponsibilitySignalModel,
)

PUBLIC_MODEL_VERSION = "public-risk-v1"
SEVERITY_WEIGHTS: dict[ResponsibilitySignalSeverity, float] = {
    ResponsibilitySignalSeverity.INFO: 1.0,
    ResponsibilitySignalSeverity.MEDIUM: 2.5,
    ResponsibilitySignalSeverity.HIGH: 4.0,
}
SIGNAL_TYPE_WEIGHTS: dict[ResponsibilitySignalType, float] = {
    ResponsibilitySignalType.DIRECT_LOOP: 3.0,
    ResponsibilitySignalType.MUTUAL_EXCHANGE: 2.0,
    ResponsibilitySignalType.CYCLE_AUTHORIZATION: 3.5,
}
RECENCY_FLOOR = 0.2
DEFAULT_SCAN_LEASE_SECONDS = 300
EDGE_STAGE_ORDER: dict[ResponsibilityEdgeType, int] = {
    ResponsibilityEdgeType.VOUCHER_ACCEPT: 1,
    ResponsibilityEdgeType.TASK_DELEGATION: 2,
    ResponsibilityEdgeType.MANUAL_LINK: 3,
}


def _sha256(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def build_edge_hash(
    *,
    source_identity_id: str,
    target_identity_id: str,
    edge_type: ResponsibilityEdgeType,
    task_id: str | None,
    voucher_id: str | None,
    metadata: dict[str, Any] | None,
) -> str:
    return _sha256(
        {
            "source_identity_id": source_identity_id,
            "target_identity_id": target_identity_id,
            "edge_type": edge_type.value,
            "task_id": task_id,
            "voucher_id": voucher_id,
            "metadata": metadata or {},
        }
    )


async def ingest_edge(
    *,
    db: AsyncSession,
    source_identity_id: str,
    target_identity_id: str,
    edge_type: ResponsibilityEdgeType,
    task_id: str | None = None,
    voucher_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ResponsibilityEdgeIngestResult:
    edge_hash = build_edge_hash(
        source_identity_id=source_identity_id,
        target_identity_id=target_identity_id,
        edge_type=edge_type,
        task_id=task_id,
        voucher_id=voucher_id,
        metadata=metadata,
    )

    existing = await db.execute(
        select(ResponsibilityEdgeModel).where(ResponsibilityEdgeModel.edge_hash == edge_hash)
    )
    edge_row = existing.scalar_one_or_none()
    if edge_row:
        existing_signals = await db.execute(
            select(ResponsibilitySignalModel).where(ResponsibilitySignalModel.edge_hash == edge_hash)
        )
        return ResponsibilityEdgeIngestResult(
            edge=_edge_to_schema(edge_row),
            signals=[_signal_to_schema(row) for row in existing_signals.scalars().all()],
        )

    edge_row = ResponsibilityEdgeModel(
        edge_hash=edge_hash,
        source_identity_id=source_identity_id,
        target_identity_id=target_identity_id,
        edge_type=edge_type.value,
        task_id=task_id,
        voucher_id=voucher_id,
        metadata_=metadata or {},
        created_at=datetime.utcnow(),
    )
    db.add(edge_row)
    await db.flush()

    signals = await _detect_signals(db=db, edge=edge_row)
    for signal in signals:
        db.add(signal)
    await db.flush()
    return ResponsibilityEdgeIngestResult(
        edge=_edge_to_schema(edge_row),
        signals=[_signal_to_schema(signal) for signal in signals],
    )


async def get_identity_signals(
    *,
    db: AsyncSession,
    identity_id: str,
    limit: int = 50,
) -> list[ResponsibilityRiskSignal]:
    result = await db.execute(
        select(ResponsibilitySignalModel)
        .where(ResponsibilitySignalModel.identity_id == identity_id)
        .order_by(ResponsibilitySignalModel.created_at.desc())
        .limit(limit)
    )
    return [_signal_to_schema(row) for row in result.scalars().all()]


async def get_task_path_summary(*, db: AsyncSession, task_id: str) -> TaskPathHashSummary:
    result = await db.execute(
        select(ResponsibilityEdgeModel)
        .where(ResponsibilityEdgeModel.task_id == task_id)
        .order_by(ResponsibilityEdgeModel.created_at.asc())
    )
    edge_hashes = [row.edge_hash for row in result.scalars().all()]
    if not edge_hashes:
        return TaskPathHashSummary(task_id=task_id, edge_hashes=[], path_hash=None)
    path_hash = _sha256({"task_id": task_id, "edge_hashes": edge_hashes})
    return TaskPathHashSummary(task_id=task_id, edge_hashes=edge_hashes, path_hash=path_hash)


async def get_identity_score(
    *,
    db: AsyncSession,
    identity_id: str,
    window_hours: int = 24,
) -> ResponsibilityScoreSummary:
    now = datetime.utcnow()
    since = now - timedelta(hours=window_hours)
    result = await db.execute(
        select(ResponsibilitySignalModel)
        .where(
            ResponsibilitySignalModel.identity_id == identity_id,
            ResponsibilitySignalModel.created_at >= since,
        )
        .order_by(ResponsibilitySignalModel.created_at.desc())
    )
    signals = result.scalars().all()
    if not signals:
        return ResponsibilityScoreSummary(
            identity_id=identity_id,
            window_hours=window_hours,
            model_version=PUBLIC_MODEL_VERSION,
            weighted_points=0.0,
            normalized_score=0.0,
            signal_count=0,
            signal_type_counts={},
            severity_counts={},
            risk_band=ResponsibilityScoreBand.LOW,
            computed_at=now,
        )

    weighted_points = 0.0
    signal_type_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for signal in signals:
        stype = ResponsibilitySignalType(signal.signal_type)
        severity = ResponsibilitySignalSeverity(signal.severity)
        age_hours = max(0.0, (now - signal.created_at).total_seconds() / 3600.0)
        if window_hours <= 0:
            recency_weight = 1.0
        else:
            recency_weight = max(RECENCY_FLOOR, 1.0 - (age_hours / window_hours))
        weighted_points += SIGNAL_TYPE_WEIGHTS[stype] * SEVERITY_WEIGHTS[severity] * recency_weight

        signal_type_counts[stype.value] = signal_type_counts.get(stype.value, 0) + 1
        severity_counts[severity.value] = severity_counts.get(severity.value, 0) + 1

    normalized_score = min(100.0, round(weighted_points, 2))
    if normalized_score >= 35:
        band = ResponsibilityScoreBand.CRITICAL
    elif normalized_score >= 20:
        band = ResponsibilityScoreBand.HIGH
    elif normalized_score >= 8:
        band = ResponsibilityScoreBand.ELEVATED
    else:
        band = ResponsibilityScoreBand.LOW

    return ResponsibilityScoreSummary(
        identity_id=identity_id,
        window_hours=window_hours,
        model_version=PUBLIC_MODEL_VERSION,
        weighted_points=round(weighted_points, 2),
        normalized_score=normalized_score,
        signal_count=len(signals),
        signal_type_counts=signal_type_counts,
        severity_counts=severity_counts,
        risk_band=band,
        computed_at=now,
    )


async def get_identity_path_features(
    *,
    db: AsyncSession,
    identity_id: str,
    window_hours: int = 24,
    max_hops: int = 4,
) -> ResponsibilityPathFeaturesSummary:
    now = datetime.utcnow()
    since = now - timedelta(hours=window_hours)
    result = await db.execute(
        select(ResponsibilityEdgeModel).where(ResponsibilityEdgeModel.created_at >= since)
    )
    edges = result.scalars().all()
    adjacency: dict[str, list[ResponsibilityEdgeModel]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source_identity_id, []).append(edge)

    traversed_edge_hashes: set[str] = set()
    reachable: set[str] = set()
    cycle_paths_detected = 0
    path_hashes_sample: list[str] = []
    seen_path_hashes: set[str] = set()

    queue: deque[tuple[str, int, list[str], list[str]]] = deque([(identity_id, 0, [], [identity_id])])
    visited_depth: dict[str, int] = {identity_id: 0}

    while queue:
        node, hops, path_hashes, path_nodes = queue.popleft()
        if hops >= max_hops:
            continue
        for edge in adjacency.get(node, []):
            traversed_edge_hashes.add(edge.edge_hash)
            next_path_hashes = [*path_hashes, edge.edge_hash]
            hashed_path = _sha256({"start": identity_id, "edge_hashes": next_path_hashes})
            if hashed_path not in seen_path_hashes and len(path_hashes_sample) < 20:
                seen_path_hashes.add(hashed_path)
                path_hashes_sample.append(hashed_path)

            target = edge.target_identity_id
            if target != identity_id:
                reachable.add(target)
            if target == identity_id or target in path_nodes:
                cycle_paths_detected += 1
                continue
            next_hops = hops + 1
            prev = visited_depth.get(target)
            if prev is None or next_hops < prev:
                visited_depth[target] = next_hops
                queue.append((target, next_hops, next_path_hashes, [*path_nodes, target]))

    return ResponsibilityPathFeaturesSummary(
        identity_id=identity_id,
        window_hours=window_hours,
        max_hops=max_hops,
        traversed_edge_count=len(traversed_edge_hashes),
        reachable_identity_count=len(reachable),
        cycle_paths_detected=cycle_paths_detected,
        path_hashes_sample=path_hashes_sample,
        computed_at=now,
    )


async def get_task_temporal_consistency_report(
    *,
    db: AsyncSession,
    task_id: str,
    burst_seconds: int = 300,
) -> TaskTemporalConsistencyReport:
    result = await db.execute(
        select(ResponsibilityEdgeModel)
        .where(ResponsibilityEdgeModel.task_id == task_id)
        .order_by(ResponsibilityEdgeModel.created_at.asc())
    )
    edges = result.scalars().all()
    issues: list[TemporalConsistencyIssue] = []
    if not edges:
        return TaskTemporalConsistencyReport(
            task_id=task_id,
            total_edges=0,
            is_consistent=True,
            issues=[],
            analyzed_at=datetime.utcnow(),
        )

    has_anchor = any(edge.edge_type == ResponsibilityEdgeType.VOUCHER_ACCEPT.value for edge in edges)
    if not has_anchor and len(edges) > 0:
        issues.append(
            TemporalConsistencyIssue(
                issue_type=TemporalConsistencyIssueType.MISSING_ANCHOR_EDGE,
                severity=ResponsibilitySignalSeverity.MEDIUM,
                detail="task has responsibility edges but no voucher_accept anchor edge",
                edge_hashes=[edge.edge_hash for edge in edges[:5]],
            )
        )

    last_stage = 0
    out_of_order_hashes: list[str] = []
    for edge in edges:
        etype = ResponsibilityEdgeType(edge.edge_type)
        stage = EDGE_STAGE_ORDER[etype]
        if stage < last_stage:
            out_of_order_hashes.append(edge.edge_hash)
        last_stage = max(last_stage, stage)
    if out_of_order_hashes:
        issues.append(
            TemporalConsistencyIssue(
                issue_type=TemporalConsistencyIssueType.EDGE_TYPE_OUT_OF_ORDER,
                severity=ResponsibilitySignalSeverity.HIGH,
                detail="edge types violated expected temporal stage ordering",
                edge_hashes=out_of_order_hashes[:20],
            )
        )

    grouped: dict[tuple[str, str, str], list[ResponsibilityEdgeModel]] = {}
    for edge in edges:
        key = (edge.source_identity_id, edge.target_identity_id, edge.edge_type)
        grouped.setdefault(key, []).append(edge)
    burst_hashes: list[str] = []
    for group_edges in grouped.values():
        if len(group_edges) < 3:
            continue
        for idx in range(len(group_edges) - 2):
            start = group_edges[idx].created_at
            end = group_edges[idx + 2].created_at
            if (end - start).total_seconds() <= burst_seconds:
                burst_hashes.extend([group_edges[idx].edge_hash, group_edges[idx + 1].edge_hash, group_edges[idx + 2].edge_hash])
                break
    if burst_hashes:
        issues.append(
            TemporalConsistencyIssue(
                issue_type=TemporalConsistencyIssueType.DUPLICATE_DIRECTION_BURST,
                severity=ResponsibilitySignalSeverity.MEDIUM,
                detail=f"detected repeated same-direction edges within {burst_seconds}s burst window",
                edge_hashes=list(dict.fromkeys(burst_hashes))[:20],
            )
        )

    return TaskTemporalConsistencyReport(
        task_id=task_id,
        total_edges=len(edges),
        is_consistent=len(issues) == 0,
        issues=issues,
        analyzed_at=datetime.utcnow(),
    )


async def run_batch_scan(
    *,
    db: AsyncSession,
    identity_ids: list[str] | None = None,
    execution_mode: ResponsibilityScanExecutionMode = ResponsibilityScanExecutionMode.SYNC,
    scan_mode: ResponsibilityScanMode = ResponsibilityScanMode.FULL,
    base_scan_id: str | None = None,
    window_hours: int = 24,
    max_hops: int = 4,
    min_score_threshold: float = 8.0,
    retry_max_attempts: int = 3,
    retry_backoff_seconds: int = 30,
) -> ResponsibilityBatchScanResult:
    now = datetime.utcnow()
    requested_identity_ids = (
        sorted({item.strip() for item in identity_ids if item and item.strip()})
        if identity_ids is not None
        else None
    )
    incremental_since_at: datetime | None = None
    if scan_mode == ResponsibilityScanMode.INCREMENTAL and not base_scan_id:
        incremental_since_at = now - timedelta(hours=window_hours)

    run_row = ResponsibilityScanRunModel(
        status=ResponsibilityScanRunStatus.PENDING.value,
        execution_mode=execution_mode.value,
        scan_mode=scan_mode.value,
        base_scan_id=base_scan_id,
        incremental_since_at=incremental_since_at,
        requested_identity_ids=requested_identity_ids,
        window_hours=window_hours,
        max_hops=max_hops,
        min_score_threshold=min_score_threshold,
        retry_max_attempts=retry_max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        current_attempt=0,
        total_identities=0,
        flagged_identities=0,
        created_at=now,
    )
    db.add(run_row)
    await db.flush()

    if execution_mode == ResponsibilityScanExecutionMode.ASYNC:
        return ResponsibilityBatchScanResult(run=_scan_run_to_schema(run_row), findings=[])

    return await execute_scan_run(db=db, scan_id=run_row.scan_id, force=True)


async def claim_next_scan_run(
    *,
    db: AsyncSession,
    runner_identity_id: str,
    lease_seconds: int = DEFAULT_SCAN_LEASE_SECONDS,
    include_failed: bool = True,
) -> ResponsibilityBatchScanRun | None:
    now = datetime.utcnow()
    claimable_lease_seconds = max(1, lease_seconds)

    pending_result = await db.execute(
        select(ResponsibilityScanRunModel)
        .where(ResponsibilityScanRunModel.status == ResponsibilityScanRunStatus.PENDING.value)
        .order_by(ResponsibilityScanRunModel.created_at.asc())
        .limit(1)
    )
    run_row = pending_result.scalar_one_or_none()

    if not run_row:
        stale_claimed_result = await db.execute(
            select(ResponsibilityScanRunModel)
            .where(
                ResponsibilityScanRunModel.status == ResponsibilityScanRunStatus.CLAIMED.value,
                ResponsibilityScanRunModel.lease_expires_at.is_not(None),
                ResponsibilityScanRunModel.lease_expires_at <= now,
            )
            .order_by(ResponsibilityScanRunModel.lease_expires_at.asc())
            .limit(1)
        )
        run_row = stale_claimed_result.scalar_one_or_none()

    if not run_row and include_failed:
        failed_result = await db.execute(
            select(ResponsibilityScanRunModel)
            .where(
                ResponsibilityScanRunModel.status == ResponsibilityScanRunStatus.FAILED.value,
                ResponsibilityScanRunModel.current_attempt < ResponsibilityScanRunModel.retry_max_attempts,
            )
            .order_by(ResponsibilityScanRunModel.next_retry_at.asc(), ResponsibilityScanRunModel.created_at.asc())
            .limit(1)
        )
        candidate = failed_result.scalar_one_or_none()
        if candidate and candidate.next_retry_at and candidate.next_retry_at > now:
            candidate = None
        run_row = candidate

    if not run_row:
        return None

    run_row.status = ResponsibilityScanRunStatus.CLAIMED.value
    run_row.claimed_by = runner_identity_id
    run_row.claimed_at = now
    run_row.lease_expires_at = now + timedelta(seconds=claimable_lease_seconds)
    run_row.last_heartbeat_at = now
    run_row.cancelled_at = None
    run_row.cancel_reason = None
    await db.flush()
    return _scan_run_to_schema(run_row)


async def heartbeat_scan_run(
    *,
    db: AsyncSession,
    scan_id: str,
    runner_identity_id: str,
    lease_seconds: int = DEFAULT_SCAN_LEASE_SECONDS,
) -> ResponsibilityBatchScanRun:
    run_row = await db.get(ResponsibilityScanRunModel, scan_id)
    if not run_row:
        raise ValueError(f"scan run {scan_id} not found")
    if run_row.status not in {
        ResponsibilityScanRunStatus.CLAIMED.value,
        ResponsibilityScanRunStatus.RUNNING.value,
    }:
        raise ValueError("scan run is not claimable for heartbeat")
    if run_row.claimed_by and run_row.claimed_by != runner_identity_id:
        raise ValueError("scan run is claimed by another runner")

    now = datetime.utcnow()
    run_row.claimed_by = runner_identity_id
    run_row.last_heartbeat_at = now
    run_row.lease_expires_at = now + timedelta(seconds=max(1, lease_seconds))
    await db.flush()
    return _scan_run_to_schema(run_row)


async def cancel_scan_run(
    *,
    db: AsyncSession,
    scan_id: str,
    runner_identity_id: str | None = None,
    reason: str | None = None,
) -> ResponsibilityBatchScanRun:
    run_row = await db.get(ResponsibilityScanRunModel, scan_id)
    if not run_row:
        raise ValueError(f"scan run {scan_id} not found")
    if run_row.status in {
        ResponsibilityScanRunStatus.COMPLETED.value,
        ResponsibilityScanRunStatus.CANCELLED.value,
    }:
        raise ValueError("scan run is already terminal and cannot be cancelled")
    if runner_identity_id and run_row.claimed_by and run_row.claimed_by != runner_identity_id:
        raise ValueError("scan run is claimed by another runner")

    now = datetime.utcnow()
    run_row.status = ResponsibilityScanRunStatus.CANCELLED.value
    run_row.cancelled_at = now
    run_row.cancel_reason = reason or "cancelled by operator"
    run_row.lease_expires_at = None
    run_row.last_heartbeat_at = None
    run_row.next_retry_at = None
    run_row.completed_at = None
    await db.flush()
    return _scan_run_to_schema(run_row)


async def execute_scan_run(
    *,
    db: AsyncSession,
    scan_id: str,
    runner_identity_id: str | None = None,
    lease_seconds: int = DEFAULT_SCAN_LEASE_SECONDS,
    force: bool = False,
    require_failed: bool = False,
) -> ResponsibilityBatchScanResult:
    run_row = await db.get(ResponsibilityScanRunModel, scan_id)
    if not run_row:
        raise ValueError(f"scan run {scan_id} not found")

    now = datetime.utcnow()
    if require_failed and run_row.status != ResponsibilityScanRunStatus.FAILED.value:
        raise ValueError("scan run is not in failed state")
    if run_row.status == ResponsibilityScanRunStatus.CANCELLED.value:
        raise ValueError("scan run is cancelled")
    if run_row.status == ResponsibilityScanRunStatus.CLAIMED.value:
        if runner_identity_id and run_row.claimed_by and run_row.claimed_by != runner_identity_id:
            raise ValueError("scan run is claimed by another runner")
        if not runner_identity_id:
            runner_identity_id = run_row.claimed_by
    if run_row.status == ResponsibilityScanRunStatus.COMPLETED.value and not force:
        result = await get_batch_scan_result(db=db, scan_id=scan_id)
        if result:
            return result
    if run_row.status == ResponsibilityScanRunStatus.RUNNING.value and not force:
        result = await get_batch_scan_result(db=db, scan_id=scan_id)
        if result:
            return result
    if run_row.status == ResponsibilityScanRunStatus.FAILED.value and not force:
        if run_row.next_retry_at and run_row.next_retry_at > now:
            raise ValueError("scan run is waiting for next retry window")
        if run_row.current_attempt >= run_row.retry_max_attempts:
            raise ValueError("scan run retry attempts exhausted")

    run_row.status = ResponsibilityScanRunStatus.RUNNING.value
    run_row.started_at = now
    run_row.current_attempt = (run_row.current_attempt or 0) + 1
    run_row.claimed_by = runner_identity_id or run_row.claimed_by
    run_row.claimed_at = run_row.claimed_at or now
    run_row.last_heartbeat_at = now
    run_row.lease_expires_at = now + timedelta(seconds=max(1, lease_seconds))
    run_row.cancelled_at = None
    run_row.cancel_reason = None
    run_row.last_error = None
    run_row.next_retry_at = None
    await db.flush()

    try:
        incremental_since_at = await _resolve_incremental_since(db=db, run_row=run_row)
        run_row.incremental_since_at = incremental_since_at
        scan_identities = await _resolve_scan_identities(db=db, run_row=run_row, incremental_since_at=incremental_since_at)

        await db.execute(
            delete(ResponsibilityScanFindingModel).where(
                ResponsibilityScanFindingModel.scan_id == run_row.scan_id
            )
        )

        findings_rows: list[ResponsibilityScanFindingModel] = []
        for identity_id in scan_identities:
            score = await get_identity_score(db=db, identity_id=identity_id, window_hours=run_row.window_hours)
            features = await get_identity_path_features(
                db=db,
                identity_id=identity_id,
                window_hours=run_row.window_hours,
                max_hops=run_row.max_hops,
            )
            should_flag = (
                score.normalized_score >= run_row.min_score_threshold
                or features.cycle_paths_detected > 0
            )
            if should_flag:
                finding = ResponsibilityScanFindingModel(
                    scan_id=run_row.scan_id,
                    identity_id=identity_id,
                    normalized_score=score.normalized_score,
                    risk_band=score.risk_band.value,
                    signal_count=score.signal_count,
                    cycle_paths_detected=features.cycle_paths_detected,
                    detail=(
                        f"window_score={score.normalized_score:.2f}, "
                        f"signals={score.signal_count}, cycles={features.cycle_paths_detected}"
                    ),
                    created_at=datetime.utcnow(),
                )
                db.add(finding)
                findings_rows.append(finding)

        run_row.total_identities = len(scan_identities)
        run_row.flagged_identities = len(findings_rows)
        run_row.status = ResponsibilityScanRunStatus.COMPLETED.value
        run_row.completed_at = datetime.utcnow()
        run_row.last_error = None
        run_row.next_retry_at = None
        _clear_claim_fields(run_row)
        await db.flush()
    except Exception as exc:
        run_row.status = ResponsibilityScanRunStatus.FAILED.value
        run_row.completed_at = None
        run_row.last_error = str(exc)
        _clear_claim_fields(run_row)
        if run_row.current_attempt < run_row.retry_max_attempts:
            backoff_seconds = max(1, run_row.retry_backoff_seconds) * run_row.current_attempt
            run_row.next_retry_at = datetime.utcnow() + timedelta(seconds=backoff_seconds)
        else:
            run_row.next_retry_at = None
        await db.flush()
        raise

    result = await get_batch_scan_result(db=db, scan_id=scan_id)
    if not result:
        raise ValueError(f"scan run {scan_id} result not found after execution")
    return result


async def get_batch_scan_result(
    *,
    db: AsyncSession,
    scan_id: str,
    findings_limit: int = 200,
) -> ResponsibilityBatchScanResult | None:
    run_row = await db.get(ResponsibilityScanRunModel, scan_id)
    if not run_row:
        return None
    findings_result = await db.execute(
        select(ResponsibilityScanFindingModel)
        .where(ResponsibilityScanFindingModel.scan_id == scan_id)
        .order_by(ResponsibilityScanFindingModel.created_at.desc())
        .limit(findings_limit)
    )
    findings = findings_result.scalars().all()
    return ResponsibilityBatchScanResult(
        run=_scan_run_to_schema(run_row),
        findings=[_scan_finding_to_schema(row) for row in findings],
    )


async def export_explainable_risk_report(
    *,
    db: AsyncSession,
    identity_id: str | None = None,
    task_id: str | None = None,
    window_hours: int = 24,
    max_hops: int = 4,
    top_signals_limit: int = 20,
    signer_identity_id: str | None = None,
    signature: str | None = None,
) -> ExplainableRiskReport:
    if bool(identity_id) == bool(task_id):
        raise ValueError("exactly one of identity_id or task_id must be provided")

    now = datetime.utcnow()
    if identity_id:
        score = await get_identity_score(db=db, identity_id=identity_id, window_hours=window_hours)
        features = await get_identity_path_features(
            db=db,
            identity_id=identity_id,
            window_hours=window_hours,
            max_hops=max_hops,
        )
        signals = await get_identity_signals(
            db=db,
            identity_id=identity_id,
            limit=top_signals_limit,
        )
        findings_rows = await db.execute(
            select(ResponsibilityScanFindingModel)
            .where(ResponsibilityScanFindingModel.identity_id == identity_id)
            .order_by(ResponsibilityScanFindingModel.created_at.desc())
            .limit(5)
        )
        findings_excerpt = [_scan_finding_to_schema(row) for row in findings_rows.scalars().all()]
        content_payload = {
            "target": "identity",
            "identity_id": identity_id,
            "score": score.model_dump(mode="json"),
            "features": features.model_dump(mode="json"),
            "signals": [item.model_dump(mode="json") for item in signals],
            "findings_excerpt": [item.model_dump(mode="json") for item in findings_excerpt],
        }
        content_hash = _sha256(content_payload)
        signature_payload_hash = _sha256(
            {
                "content_hash": content_hash,
                "target": "identity",
                "identity_id": identity_id,
                "window_hours": window_hours,
                "max_hops": max_hops,
            }
        )
        return ExplainableRiskReport(
            target=ExplainableRiskReportTarget.IDENTITY,
            identity_id=identity_id,
            window_hours=window_hours,
            max_hops=max_hops,
            generated_at=now,
            content_hash=content_hash,
            score_summary=score,
            path_features=features,
            top_signals=signals,
            findings_excerpt=findings_excerpt,
            signature=ReportSignaturePlaceholder(
                signer_identity_id=signer_identity_id,
                signature_payload_hash=signature_payload_hash,
                signature=signature,
                status=ReportSignatureStatus.PROVIDED if signature else ReportSignatureStatus.UNSIGNED,
            ),
        )

    task_id_value = task_id or ""
    task_summary = await get_task_path_summary(db=db, task_id=task_id_value)
    temporal_report = await get_task_temporal_consistency_report(db=db, task_id=task_id_value)
    signals_result = await db.execute(
        select(ResponsibilitySignalModel)
        .where(ResponsibilitySignalModel.task_id == task_id_value)
        .order_by(ResponsibilitySignalModel.created_at.desc())
        .limit(top_signals_limit)
    )
    signals = [_signal_to_schema(row) for row in signals_result.scalars().all()]
    content_payload = {
        "target": "task",
        "task_id": task_id_value,
        "task_path_summary": task_summary.model_dump(mode="json"),
        "temporal_consistency": temporal_report.model_dump(mode="json"),
        "signals": [item.model_dump(mode="json") for item in signals],
    }
    content_hash = _sha256(content_payload)
    signature_payload_hash = _sha256(
        {
            "content_hash": content_hash,
            "target": "task",
            "task_id": task_id_value,
            "window_hours": window_hours,
            "max_hops": max_hops,
        }
    )
    return ExplainableRiskReport(
        target=ExplainableRiskReportTarget.TASK,
        task_id=task_id_value,
        window_hours=window_hours,
        max_hops=max_hops,
        generated_at=now,
        content_hash=content_hash,
        task_path_summary=task_summary,
        temporal_consistency=temporal_report,
        top_signals=signals,
        findings_excerpt=[],
        signature=ReportSignaturePlaceholder(
            signer_identity_id=signer_identity_id,
            signature_payload_hash=signature_payload_hash,
            signature=signature,
            status=ReportSignatureStatus.PROVIDED if signature else ReportSignatureStatus.UNSIGNED,
        ),
    )


def get_public_risk_model() -> ResponsibilityPublicRiskModel:
    return ResponsibilityPublicRiskModel(
        model_version=PUBLIC_MODEL_VERSION,
        severity_weights={key.value: value for key, value in SEVERITY_WEIGHTS.items()},
        signal_type_weights={key.value: value for key, value in SIGNAL_TYPE_WEIGHTS.items()},
        recency_floor=RECENCY_FLOOR,
        public_band_reference={
            "low_min": 0.0,
            "elevated_min": 8.0,
            "high_min": 20.0,
            "critical_min": 35.0,
        },
    )


async def _detect_signals(
    *,
    db: AsyncSession,
    edge: ResponsibilityEdgeModel,
) -> list[ResponsibilitySignalModel]:
    signals: list[ResponsibilitySignalModel] = []

    if edge.source_identity_id == edge.target_identity_id:
        signals.append(
            ResponsibilitySignalModel(
                signal_type=ResponsibilitySignalType.DIRECT_LOOP.value,
                severity=ResponsibilitySignalSeverity.HIGH.value,
                identity_id=edge.source_identity_id,
                edge_hash=edge.edge_hash,
                related_edge_hashes=[edge.edge_hash],
                task_id=edge.task_id,
                detail="source and target identities are identical",
                created_at=datetime.utcnow(),
            )
        )

    reverse_result = await db.execute(
        select(ResponsibilityEdgeModel)
        .where(
            ResponsibilityEdgeModel.source_identity_id == edge.target_identity_id,
            ResponsibilityEdgeModel.target_identity_id == edge.source_identity_id,
            ResponsibilityEdgeModel.edge_hash != edge.edge_hash,
        )
        .order_by(ResponsibilityEdgeModel.created_at.desc())
        .limit(1)
    )
    reverse = reverse_result.scalar_one_or_none()
    if reverse:
        signals.append(
            ResponsibilitySignalModel(
                signal_type=ResponsibilitySignalType.MUTUAL_EXCHANGE.value,
                severity=ResponsibilitySignalSeverity.MEDIUM.value,
                identity_id=edge.source_identity_id,
                edge_hash=edge.edge_hash,
                related_edge_hashes=[edge.edge_hash, reverse.edge_hash],
                task_id=edge.task_id,
                detail="detected reverse direction authorization edge",
                created_at=datetime.utcnow(),
            )
        )

    cycle_hashes = await _find_cycle_path_hashes(
        db=db,
        start=edge.target_identity_id,
        target=edge.source_identity_id,
        max_hops=6,
    )
    if cycle_hashes:
        signals.append(
            ResponsibilitySignalModel(
                signal_type=ResponsibilitySignalType.CYCLE_AUTHORIZATION.value,
                severity=ResponsibilitySignalSeverity.HIGH.value,
                identity_id=edge.source_identity_id,
                edge_hash=edge.edge_hash,
                related_edge_hashes=[edge.edge_hash, *cycle_hashes],
                task_id=edge.task_id,
                detail="authorization cycle detected in responsibility graph",
                created_at=datetime.utcnow(),
            )
        )

    return signals


async def _find_cycle_path_hashes(
    *,
    db: AsyncSession,
    start: str,
    target: str,
    max_hops: int = 6,
) -> list[str]:
    if start == target:
        return []

    queue: deque[tuple[str, list[str], int]] = deque([(start, [], 0)])
    visited: set[tuple[str, int]] = set()
    while queue:
        node, path_hashes, hops = queue.popleft()
        if hops >= max_hops:
            continue
        key = (node, hops)
        if key in visited:
            continue
        visited.add(key)

        result = await db.execute(
            select(ResponsibilityEdgeModel).where(ResponsibilityEdgeModel.source_identity_id == node)
        )
        for edge in result.scalars().all():
            next_path = [*path_hashes, edge.edge_hash]
            if edge.target_identity_id == target:
                return next_path
            queue.append((edge.target_identity_id, next_path, hops + 1))
    return []


def _edge_to_schema(row: ResponsibilityEdgeModel) -> ResponsibilityEdge:
    return ResponsibilityEdge(
        edge_id=row.edge_id,
        edge_hash=row.edge_hash,
        source_identity_id=row.source_identity_id,
        target_identity_id=row.target_identity_id,
        edge_type=ResponsibilityEdgeType(row.edge_type),
        task_id=row.task_id,
        voucher_id=row.voucher_id,
        metadata=row.metadata_ or {},
        created_at=row.created_at,
    )


def _signal_to_schema(row: ResponsibilitySignalModel) -> ResponsibilityRiskSignal:
    return ResponsibilityRiskSignal(
        signal_id=row.signal_id,
        signal_type=ResponsibilitySignalType(row.signal_type),
        severity=ResponsibilitySignalSeverity(row.severity),
        identity_id=row.identity_id,
        edge_hash=row.edge_hash,
        related_edge_hashes=row.related_edge_hashes or [],
        task_id=row.task_id,
        detail=row.detail,
        created_at=row.created_at,
    )


def _scan_run_to_schema(row: ResponsibilityScanRunModel) -> ResponsibilityBatchScanRun:
    return ResponsibilityBatchScanRun(
        scan_id=row.scan_id,
        status=ResponsibilityScanRunStatus(row.status),
        execution_mode=ResponsibilityScanExecutionMode(row.execution_mode),
        scan_mode=ResponsibilityScanMode(row.scan_mode),
        base_scan_id=row.base_scan_id,
        incremental_since_at=row.incremental_since_at,
        requested_identity_ids=row.requested_identity_ids,
        window_hours=row.window_hours,
        max_hops=row.max_hops,
        min_score_threshold=row.min_score_threshold,
        retry_max_attempts=row.retry_max_attempts,
        retry_backoff_seconds=row.retry_backoff_seconds,
        current_attempt=row.current_attempt,
        claimed_by=row.claimed_by,
        claimed_at=row.claimed_at,
        lease_expires_at=row.lease_expires_at,
        last_heartbeat_at=row.last_heartbeat_at,
        started_at=row.started_at,
        next_retry_at=row.next_retry_at,
        last_error=row.last_error,
        cancelled_at=row.cancelled_at,
        cancel_reason=row.cancel_reason,
        total_identities=row.total_identities,
        flagged_identities=row.flagged_identities,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _scan_finding_to_schema(row: ResponsibilityScanFindingModel) -> ResponsibilityScanFinding:
    return ResponsibilityScanFinding(
        finding_id=row.finding_id,
        scan_id=row.scan_id,
        identity_id=row.identity_id,
        normalized_score=row.normalized_score,
        risk_band=ResponsibilityScoreBand(row.risk_band),
        signal_count=row.signal_count,
        cycle_paths_detected=row.cycle_paths_detected,
        detail=row.detail,
        created_at=row.created_at,
    )


def _clear_claim_fields(run_row: ResponsibilityScanRunModel) -> None:
    run_row.claimed_by = None
    run_row.claimed_at = None
    run_row.lease_expires_at = None
    run_row.last_heartbeat_at = None


async def _resolve_incremental_since(
    *,
    db: AsyncSession,
    run_row: ResponsibilityScanRunModel,
) -> datetime | None:
    if run_row.scan_mode != ResponsibilityScanMode.INCREMENTAL.value:
        return None
    if run_row.base_scan_id:
        base_run = await db.get(ResponsibilityScanRunModel, run_row.base_scan_id)
        if not base_run:
            raise ValueError(f"base scan run not found: {run_row.base_scan_id}")
        return base_run.completed_at or base_run.created_at
    if run_row.incremental_since_at:
        return run_row.incremental_since_at
    return datetime.utcnow() - timedelta(hours=run_row.window_hours)


async def _resolve_scan_identities(
    *,
    db: AsyncSession,
    run_row: ResponsibilityScanRunModel,
    incremental_since_at: datetime | None,
) -> list[str]:
    if run_row.requested_identity_ids:
        return sorted({item.strip() for item in run_row.requested_identity_ids if item and item.strip()})

    since = incremental_since_at or (datetime.utcnow() - timedelta(hours=run_row.window_hours))
    source_rows = await db.execute(
        select(ResponsibilityEdgeModel.source_identity_id).where(
            ResponsibilityEdgeModel.created_at >= since
        )
    )
    target_rows = await db.execute(
        select(ResponsibilityEdgeModel.target_identity_id).where(
            ResponsibilityEdgeModel.created_at >= since
        )
    )
    signal_rows = await db.execute(
        select(ResponsibilitySignalModel.identity_id).where(
            ResponsibilitySignalModel.created_at >= since
        )
    )
    id_set = {
        *(item for item in source_rows.scalars().all() if item),
        *(item for item in target_rows.scalars().all() if item),
        *(item for item in signal_rows.scalars().all() if item),
    }
    return sorted(id_set)

