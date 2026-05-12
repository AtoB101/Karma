"""Responsibility graph ingestion and public-safe risk signal detection."""
from __future__ import annotations

import hashlib
import json
from collections import deque
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import (
    ResponsibilityEdge,
    ResponsibilityEdgeIngestResult,
    ResponsibilityEdgeType,
    ResponsibilityRiskSignal,
    ResponsibilitySignalSeverity,
    ResponsibilitySignalType,
    ResponsibilityScoreBand,
    ResponsibilityScoreSummary,
    ResponsibilityPublicRiskModel,
    TaskPathHashSummary,
)
from db.models.orm import ResponsibilityEdgeModel, ResponsibilitySignalModel

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

