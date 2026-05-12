from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.schemas import (
    ResponsibilityEdgeType,
    ResponsibilityScanExecutionMode,
    ResponsibilityScanMode,
)
from db.models.orm import ResponsibilityScanRunModel, ResponsibilitySignalModel
from services.responsibility_graph import (
    cancel_scan_run,
    claim_next_scan_run,
    heartbeat_scan_run,
    execute_scan_run,
    export_explainable_risk_report,
    get_batch_scan_result,
    get_task_temporal_consistency_report,
    get_identity_path_features,
    get_identity_score,
    ingest_edge,
    run_batch_scan,
)


@pytest.mark.asyncio
async def test_identity_score_filters_signals_by_time_window(db_session):
    identity_id = "identity-window-001"
    now = datetime.utcnow()

    # Old signal should be excluded by 24h window
    db_session.add(
        ResponsibilitySignalModel(
            signal_type="cycle_authorization",
            severity="high",
            identity_id=identity_id,
            edge_hash="a" * 64,
            related_edge_hashes=["a" * 64],
            task_id="task-1",
            detail="old cycle",
            created_at=now - timedelta(hours=48),
        )
    )
    # Recent signal should be included
    db_session.add(
        ResponsibilitySignalModel(
            signal_type="mutual_exchange",
            severity="medium",
            identity_id=identity_id,
            edge_hash="b" * 64,
            related_edge_hashes=["b" * 64],
            task_id="task-2",
            detail="recent reverse edge",
            created_at=now - timedelta(hours=2),
        )
    )
    await db_session.flush()

    score_24h = await get_identity_score(db=db_session, identity_id=identity_id, window_hours=24)
    assert score_24h.signal_count == 1
    assert score_24h.signal_type_counts == {"mutual_exchange": 1}
    assert score_24h.weighted_points > 0

    score_72h = await get_identity_score(db=db_session, identity_id=identity_id, window_hours=72)
    assert score_72h.signal_count == 2
    assert score_72h.signal_type_counts["cycle_authorization"] == 1


@pytest.mark.asyncio
async def test_path_features_detect_cycle(db_session):
    await ingest_edge(
        db=db_session,
        source_identity_id="id-a",
        target_identity_id="id-b",
        edge_type=ResponsibilityEdgeType.MANUAL_LINK,
    )
    await ingest_edge(
        db=db_session,
        source_identity_id="id-b",
        target_identity_id="id-c",
        edge_type=ResponsibilityEdgeType.MANUAL_LINK,
    )
    await ingest_edge(
        db=db_session,
        source_identity_id="id-c",
        target_identity_id="id-a",
        edge_type=ResponsibilityEdgeType.MANUAL_LINK,
    )

    features = await get_identity_path_features(
        db=db_session,
        identity_id="id-a",
        window_hours=24,
        max_hops=4,
    )
    assert features.traversed_edge_count >= 3
    assert features.reachable_identity_count >= 2
    assert features.cycle_paths_detected >= 1


@pytest.mark.asyncio
async def test_batch_scan_returns_flagged_findings(db_session):
    await ingest_edge(
        db=db_session,
        source_identity_id="scan-a",
        target_identity_id="scan-b",
        edge_type=ResponsibilityEdgeType.MANUAL_LINK,
    )
    await ingest_edge(
        db=db_session,
        source_identity_id="scan-b",
        target_identity_id="scan-a",
        edge_type=ResponsibilityEdgeType.MANUAL_LINK,
    )

    result = await run_batch_scan(
        db=db_session,
        identity_ids=["scan-a", "scan-b"],
        window_hours=24,
        max_hops=4,
        min_score_threshold=1.0,
    )
    assert result.run.status.value == "completed"
    assert result.run.total_identities == 2
    assert result.run.flagged_identities >= 1
    assert len(result.findings) >= 1


@pytest.mark.asyncio
async def test_incremental_batch_scan_uses_base_scan(db_session):
    await ingest_edge(
        db=db_session,
        source_identity_id="inc-a",
        target_identity_id="inc-b",
        edge_type=ResponsibilityEdgeType.MANUAL_LINK,
    )
    base = await run_batch_scan(
        db=db_session,
        identity_ids=None,
        scan_mode=ResponsibilityScanMode.FULL,
        window_hours=24,
        max_hops=4,
        min_score_threshold=0.0,
    )

    await ingest_edge(
        db=db_session,
        source_identity_id="inc-a",
        target_identity_id="inc-c",
        edge_type=ResponsibilityEdgeType.MANUAL_LINK,
    )
    incremental = await run_batch_scan(
        db=db_session,
        identity_ids=None,
        scan_mode=ResponsibilityScanMode.INCREMENTAL,
        base_scan_id=base.run.scan_id,
        window_hours=24,
        max_hops=4,
        min_score_threshold=0.0,
    )
    assert incremental.run.scan_mode.value == "incremental"
    assert incremental.run.base_scan_id == base.run.scan_id
    assert incremental.run.total_identities >= 1


@pytest.mark.asyncio
async def test_async_scan_run_create_then_execute(db_session):
    await ingest_edge(
        db=db_session,
        source_identity_id="async-a",
        target_identity_id="async-b",
        edge_type=ResponsibilityEdgeType.MANUAL_LINK,
    )

    created = await run_batch_scan(
        db=db_session,
        identity_ids=["async-a", "async-b"],
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        window_hours=24,
        max_hops=4,
        min_score_threshold=0.0,
    )
    assert created.run.status.value == "pending"
    assert created.run.current_attempt == 0
    assert created.findings == []

    polled = await get_batch_scan_result(db=db_session, scan_id=created.run.scan_id)
    assert polled is not None
    assert polled.run.status.value == "pending"

    executed = await execute_scan_run(db=db_session, scan_id=created.run.scan_id)
    assert executed.run.status.value == "completed"
    assert executed.run.current_attempt == 1
    assert executed.run.total_identities == 2


@pytest.mark.asyncio
async def test_async_scan_run_failure_sets_retry_window(db_session):
    created = await run_batch_scan(
        db=db_session,
        identity_ids=None,
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.INCREMENTAL,
        base_scan_id="missing-base-scan",
        retry_max_attempts=2,
        retry_backoff_seconds=60,
    )

    with pytest.raises(ValueError, match="base scan run not found"):
        await execute_scan_run(db=db_session, scan_id=created.run.scan_id)

    failed = await get_batch_scan_result(db=db_session, scan_id=created.run.scan_id)
    assert failed is not None
    assert failed.run.status.value == "failed"
    assert failed.run.current_attempt == 1
    assert failed.run.next_retry_at is not None
    assert failed.run.last_error is not None

    with pytest.raises(ValueError, match="waiting for next retry window"):
        await execute_scan_run(
            db=db_session,
            scan_id=created.run.scan_id,
            require_failed=True,
        )


@pytest.mark.asyncio
async def test_claim_heartbeat_cancel_scan_run(db_session):
    created = await run_batch_scan(
        db=db_session,
        identity_ids=["ops-a"],
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.FULL,
    )
    scan_id = created.run.scan_id

    claimed = await claim_next_scan_run(
        db=db_session,
        runner_identity_id="runner-1",
        lease_seconds=120,
    )
    assert claimed is not None
    assert claimed.scan_id == scan_id
    assert claimed.status.value == "claimed"
    assert claimed.claimed_by == "runner-1"
    assert claimed.lease_expires_at is not None

    heartbeated = await heartbeat_scan_run(
        db=db_session,
        scan_id=scan_id,
        runner_identity_id="runner-1",
        lease_seconds=180,
    )
    assert heartbeated.last_heartbeat_at is not None
    assert heartbeated.lease_expires_at is not None
    assert heartbeated.status.value == "claimed"

    cancelled = await cancel_scan_run(
        db=db_session,
        scan_id=scan_id,
        runner_identity_id="runner-1",
        reason="worker shutdown",
    )
    assert cancelled.status.value == "cancelled"
    assert cancelled.cancel_reason == "worker shutdown"

    with pytest.raises(ValueError, match="cancelled"):
        await execute_scan_run(db=db_session, scan_id=scan_id)


@pytest.mark.asyncio
async def test_claim_reacquires_stale_claimed_scan_run(db_session):
    created = await run_batch_scan(
        db=db_session,
        identity_ids=["ops-b"],
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
    )
    scan_id = created.run.scan_id
    first_claim = await claim_next_scan_run(
        db=db_session,
        runner_identity_id="runner-1",
        lease_seconds=1,
    )
    assert first_claim is not None
    assert first_claim.status.value == "claimed"

    row = await db_session.get(ResponsibilityScanRunModel, scan_id)
    assert row is not None
    row.lease_expires_at = datetime.utcnow() - timedelta(seconds=5)
    await db_session.flush()

    second_claim = await claim_next_scan_run(
        db=db_session,
        runner_identity_id="runner-2",
        lease_seconds=60,
    )
    assert second_claim is not None
    assert second_claim.scan_id == scan_id
    assert second_claim.claimed_by == "runner-2"


@pytest.mark.asyncio
async def test_task_temporal_consistency_missing_anchor_issue(db_session):
    task_id = "task-temporal-001"
    await ingest_edge(
        db=db_session,
        source_identity_id="temp-a",
        target_identity_id="temp-b",
        edge_type=ResponsibilityEdgeType.TASK_DELEGATION,
        task_id=task_id,
    )
    report = await get_task_temporal_consistency_report(db=db_session, task_id=task_id)
    assert report.task_id == task_id
    assert report.is_consistent is False
    assert any(issue.issue_type.value == "missing_anchor_edge" for issue in report.issues)


@pytest.mark.asyncio
async def test_export_explainable_report_identity_and_task(db_session):
    task_id = "task-report-001"
    await ingest_edge(
        db=db_session,
        source_identity_id="exp-a",
        target_identity_id="exp-b",
        edge_type=ResponsibilityEdgeType.VOUCHER_ACCEPT,
        task_id=task_id,
    )
    await ingest_edge(
        db=db_session,
        source_identity_id="exp-b",
        target_identity_id="exp-c",
        edge_type=ResponsibilityEdgeType.TASK_DELEGATION,
        task_id=task_id,
    )

    identity_report = await export_explainable_risk_report(
        db=db_session,
        identity_id="exp-a",
        window_hours=24,
        max_hops=4,
    )
    assert identity_report.target.value == "identity"
    assert identity_report.identity_id == "exp-a"
    assert identity_report.content_hash

    task_report = await export_explainable_risk_report(
        db=db_session,
        task_id=task_id,
        window_hours=24,
        max_hops=4,
    )
    assert task_report.target.value == "task"
    assert task_report.task_id == task_id
    assert task_report.temporal_consistency is not None

