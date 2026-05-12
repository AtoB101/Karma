from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.schemas import ResponsibilityEdgeType
from db.models.orm import ResponsibilitySignalModel
from services.responsibility_graph import (
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

