from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.schemas import (
    ResponsibilityEdgeType,
    ResponsibilityScanEventType,
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
    list_dead_letter_scan_runs,
    list_scan_run_events,
    get_scan_runner_activity,
    get_scan_ops_alerts,
    get_scan_run_ops_report,
    get_scan_run_queue_stats,
    get_task_temporal_consistency_report,
    get_identity_path_features,
    get_identity_score,
    ingest_edge,
    pull_and_execute_scan_run,
    purge_dead_letter_scan_runs,
    requeue_dead_letter_scan_run,
    requeue_dead_letter_scan_runs,
    recover_stale_scan_runs,
    run_scan_queue_maintenance_tick,
    run_batch_scan,
    sweep_dead_letter_scan_runs,
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
    events = await list_scan_run_events(db=db_session, scan_id=created.run.scan_id)
    event_types = {item.event_type for item in events}
    assert ResponsibilityScanEventType.EXECUTION_FAILED in event_types


@pytest.mark.asyncio
async def test_dead_letter_sweep_list_and_requeue(db_session):
    created = await run_batch_scan(
        db=db_session,
        identity_ids=None,
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.INCREMENTAL,
        base_scan_id="missing-base-dlq",
        retry_max_attempts=1,
        retry_backoff_seconds=10,
    )
    scan_id = created.run.scan_id
    with pytest.raises(ValueError, match="base scan run not found"):
        await execute_scan_run(db=db_session, scan_id=scan_id)

    sweep = await sweep_dead_letter_scan_runs(db=db_session, limit=100, reason="exhausted retries")
    assert sweep.dead_lettered_count >= 1
    assert scan_id in sweep.dead_lettered_scan_ids

    dead_letter_runs = await list_dead_letter_scan_runs(db=db_session, limit=100)
    dead_letter_ids = {item.scan_id for item in dead_letter_runs}
    assert scan_id in dead_letter_ids

    requeued = await requeue_dead_letter_scan_run(
        db=db_session,
        scan_id=scan_id,
        reason="operator requeue",
    )
    assert requeued.status.value == "pending"
    assert requeued.current_attempt == 0
    assert requeued.dead_lettered_at is None

    events = await list_scan_run_events(db=db_session, scan_id=scan_id)
    event_types = {item.event_type for item in events}
    assert ResponsibilityScanEventType.DEAD_LETTERED in event_types
    assert ResponsibilityScanEventType.REQUEUED in event_types


@pytest.mark.asyncio
async def test_dead_letter_batch_requeue_and_purge(db_session):
    created = await run_batch_scan(
        db=db_session,
        identity_ids=None,
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.INCREMENTAL,
        base_scan_id="missing-base-dlq-batch",
        retry_max_attempts=1,
        retry_backoff_seconds=10,
    )
    scan_id = created.run.scan_id
    with pytest.raises(ValueError, match="base scan run not found"):
        await execute_scan_run(db=db_session, scan_id=scan_id)

    sweep = await sweep_dead_letter_scan_runs(db=db_session, limit=100, reason="batch-exhausted")
    assert scan_id in sweep.dead_lettered_scan_ids

    requeue_batch = await requeue_dead_letter_scan_runs(db=db_session, limit=100, reason="ops-batch")
    assert requeue_batch.requeued_count >= 1
    assert scan_id in requeue_batch.requeued_scan_ids

    row = await db_session.get(ResponsibilityScanRunModel, scan_id)
    assert row is not None
    row.status = "dead_letter"
    row.dead_lettered_at = datetime.utcnow() - timedelta(hours=2)
    row.dead_letter_reason = "manual-old-dlq"
    await db_session.flush()

    purge = await purge_dead_letter_scan_runs(db=db_session, limit=100, older_than_hours=1)
    assert purge.purged_count >= 1
    assert scan_id in purge.purged_scan_ids
    assert await db_session.get(ResponsibilityScanRunModel, scan_id) is None


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
async def test_scan_queue_stats_and_recover_stale_runs(db_session):
    created = await run_batch_scan(
        db=db_session,
        identity_ids=["ops-c"],
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.FULL,
    )
    scan_id = created.run.scan_id

    claimed = await claim_next_scan_run(
        db=db_session,
        runner_identity_id="runner-stale",
        lease_seconds=60,
    )
    assert claimed is not None
    row = await db_session.get(ResponsibilityScanRunModel, scan_id)
    assert row is not None
    row.lease_expires_at = datetime.utcnow() - timedelta(seconds=10)
    await db_session.flush()

    stats_before = await get_scan_run_queue_stats(db=db_session)
    assert stats_before.stale_claimed >= 1
    assert stats_before.status_counts.get("claimed", 0) >= 1

    recovered = await recover_stale_scan_runs(db=db_session, limit=100)
    assert recovered.recovered_count >= 1
    assert scan_id in recovered.recovered_scan_ids

    refreshed = await db_session.get(ResponsibilityScanRunModel, scan_id)
    assert refreshed is not None
    assert refreshed.status == "pending"
    assert refreshed.claimed_by is None

    stats_after = await get_scan_run_queue_stats(db=db_session)
    assert stats_after.stale_claimed == 0
    assert stats_after.claimable_pending >= 1
    events = await list_scan_run_events(db=db_session, scan_id=scan_id)
    event_types = {item.event_type for item in events}
    assert ResponsibilityScanEventType.STALE_RECOVERED in event_types


@pytest.mark.asyncio
async def test_scan_ops_report_contains_recent_events_and_failures(db_session):
    created = await run_batch_scan(
        db=db_session,
        identity_ids=None,
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.INCREMENTAL,
        base_scan_id="missing-base-ops-report",
        retry_max_attempts=1,
        retry_backoff_seconds=10,
    )
    scan_id = created.run.scan_id
    with pytest.raises(ValueError, match="base scan run not found"):
        await execute_scan_run(
            db=db_session,
            scan_id=scan_id,
            runner_identity_id="runner-ops-report",
        )
    await sweep_dead_letter_scan_runs(db=db_session, limit=100, reason="ops-report-dlq")

    report = await get_scan_run_ops_report(
        db=db_session,
        window_hours=24,
        recent_events_limit=50,
        top_failure_limit=10,
    )
    assert report.window_hours == 24
    assert report.total_runs >= 1
    assert report.dead_letter_count >= 1
    assert len(report.recent_events) >= 1
    event_types = {item.event_type for item in report.recent_events}
    assert ResponsibilityScanEventType.CREATED in event_types
    assert ResponsibilityScanEventType.DEAD_LETTERED in event_types
    assert len(report.top_failure_reasons) >= 1
    assert any("base scan run not found" in item.reason for item in report.top_failure_reasons)
    assert any(item.runner_identity_id == "runner-ops-report" for item in report.runner_activity)
    assert any(item.alert_type.value == "queue_failure_ratio" for item in report.alerts)


@pytest.mark.asyncio
async def test_scan_ops_alerts_detect_runner_failure_spike(db_session):
    created = await run_batch_scan(
        db=db_session,
        identity_ids=None,
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.INCREMENTAL,
        base_scan_id="missing-base-alerts",
        retry_max_attempts=3,
        retry_backoff_seconds=1,
    )
    scan_id = created.run.scan_id
    for _ in range(3):
        with pytest.raises(ValueError, match="base scan run not found"):
            await execute_scan_run(
                db=db_session,
                scan_id=scan_id,
                runner_identity_id="runner-alert-1",
                force=True,
            )

    alerts = await get_scan_ops_alerts(
        db=db_session,
        window_hours=24,
        runner_limit=20,
        dead_letter_threshold=100,
        stale_threshold=100,
        failed_ratio_threshold=0.9,
        runner_failure_min_started=2,
        runner_failure_ratio_threshold=0.5,
    )
    assert any(item.alert_type.value == "runner_failure_spike" for item in alerts)


@pytest.mark.asyncio
async def test_scan_runner_activity_summary_counts(db_session):
    created = await run_batch_scan(
        db=db_session,
        identity_ids=["runner-a"],
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.FULL,
    )
    scan_id = created.run.scan_id
    await claim_next_scan_run(
        db=db_session,
        runner_identity_id="runner-activity-1",
        lease_seconds=120,
    )
    await heartbeat_scan_run(
        db=db_session,
        scan_id=scan_id,
        runner_identity_id="runner-activity-1",
        lease_seconds=120,
    )
    await execute_scan_run(
        db=db_session,
        scan_id=scan_id,
        runner_identity_id="runner-activity-1",
        lease_seconds=120,
    )

    activity = await get_scan_runner_activity(
        db=db_session,
        window_hours=24,
        limit=20,
    )
    summary = next(item for item in activity if item.runner_identity_id == "runner-activity-1")
    assert summary.claimed_count >= 1
    assert summary.heartbeat_count >= 1
    assert summary.execution_started_count >= 1
    assert summary.execution_completed_count >= 1


@pytest.mark.asyncio
async def test_pull_execute_scan_run_idle_and_completed(db_session):
    idle = await pull_and_execute_scan_run(
        db=db_session,
        runner_identity_id="runner-empty",
    )
    assert idle.outcome.value == "idle"

    created = await run_batch_scan(
        db=db_session,
        identity_ids=["pull-a"],
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.FULL,
        min_score_threshold=0.0,
    )
    result = await pull_and_execute_scan_run(
        db=db_session,
        runner_identity_id="runner-pull",
        lease_seconds=120,
    )
    assert result.outcome.value == "completed"
    assert result.claimed_scan_id == created.run.scan_id
    assert result.run is not None
    assert result.run.status.value == "completed"


@pytest.mark.asyncio
async def test_scan_queue_maintenance_tick_executes_jobs(db_session):
    await run_batch_scan(
        db=db_session,
        identity_ids=["mt-a"],
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.FULL,
        min_score_threshold=0.0,
    )
    await run_batch_scan(
        db=db_session,
        identity_ids=["mt-b"],
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.FULL,
        min_score_threshold=0.0,
    )

    tick = await run_scan_queue_maintenance_tick(
        db=db_session,
        runner_identity_id="runner-maint",
        recover_limit=50,
        max_claim_execute=2,
        lease_seconds=120,
        include_failed=True,
    )
    assert tick.recover_limit == 50
    assert tick.max_claim_execute == 2
    assert tick.claimed_count == 2
    assert tick.executed_count == 2
    assert tick.failed_count == 0
    assert len(tick.executed_scan_ids) == 2


@pytest.mark.asyncio
async def test_scan_run_event_timeline_contains_lifecycle_events(db_session):
    created = await run_batch_scan(
        db=db_session,
        identity_ids=["evt-a"],
        execution_mode=ResponsibilityScanExecutionMode.ASYNC,
        scan_mode=ResponsibilityScanMode.FULL,
        min_score_threshold=0.0,
    )
    scan_id = created.run.scan_id
    await claim_next_scan_run(
        db=db_session,
        runner_identity_id="runner-evt",
        lease_seconds=120,
    )
    await heartbeat_scan_run(
        db=db_session,
        scan_id=scan_id,
        runner_identity_id="runner-evt",
        lease_seconds=120,
    )
    await execute_scan_run(
        db=db_session,
        scan_id=scan_id,
        runner_identity_id="runner-evt",
        lease_seconds=120,
    )
    events = await list_scan_run_events(db=db_session, scan_id=scan_id)
    event_types = [item.event_type for item in events]
    assert event_types[0] == ResponsibilityScanEventType.CREATED
    assert ResponsibilityScanEventType.CLAIMED in event_types
    assert ResponsibilityScanEventType.HEARTBEAT in event_types
    assert ResponsibilityScanEventType.EXECUTION_STARTED in event_types
    assert ResponsibilityScanEventType.EXECUTION_COMPLETED in event_types


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

