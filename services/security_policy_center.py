"""
Karma Security Policy Center
Persistent policy versioning, canary rollout, and rollback helpers.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import (
    SecurityThresholdPolicy,
    SecurityThresholdPolicyResolveResult,
    SecurityThresholdPolicyStatus,
)
from db.models.orm import SecurityThresholdPolicyModel

DEFAULT_SECURITY_POLICY_CONFIG: dict[str, Any] = {
    "window_minutes": 15,
    "failed_auth_threshold": 10,
    "rate_limit_threshold": 30,
    "private_runtime_error_threshold": 5,
    "private_runtime_error_rate_threshold": 0.25,
    "private_runtime_min_requests": 10,
    "dimension_limit": 5,
    "alert_cooldown_minutes": 10,
    "failed_auth_threshold_overrides": "",
    "rate_limit_threshold_overrides": "",
    "private_runtime_error_threshold_overrides": "",
    "private_runtime_error_rate_threshold_overrides": "",
    "baseline_window_minutes": 24 * 60,
    "baseline_drift_multiplier": 2.5,
    "baseline_min_sample_count": 3,
    "baseline_capture_interval_minutes": 10,
}


def _to_schema(row: SecurityThresholdPolicyModel) -> SecurityThresholdPolicy:
    return SecurityThresholdPolicy(
        policy_id=row.policy_id,
        version=row.version,
        status=SecurityThresholdPolicyStatus(row.status),
        rollout_percent=row.rollout_percent,
        config=dict(row.config or {}),
        note=row.note,
        created_by=row.created_by,
        created_at=row.created_at,
        activated_at=row.activated_at,
        archived_at=row.archived_at,
        parent_policy_id=row.parent_policy_id,
    )


def merge_security_policy_defaults(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_SECURITY_POLICY_CONFIG)
    if config:
        merged.update(config)
    return merged


async def list_security_threshold_policies(
    db: AsyncSession,
    *,
    status: SecurityThresholdPolicyStatus | None = None,
    limit: int = 50,
) -> list[SecurityThresholdPolicy]:
    stmt = select(SecurityThresholdPolicyModel).order_by(SecurityThresholdPolicyModel.version.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(SecurityThresholdPolicyModel.status == status.value)
    result = await db.execute(stmt)
    return [_to_schema(item) for item in result.scalars().all()]


async def get_security_threshold_policy(
    db: AsyncSession,
    *,
    policy_id: str,
) -> SecurityThresholdPolicy | None:
    row = await db.get(SecurityThresholdPolicyModel, policy_id)
    if row is None:
        return None
    return _to_schema(row)


async def create_security_threshold_policy(
    db: AsyncSession,
    *,
    config: dict[str, Any] | None = None,
    note: str | None = None,
    created_by: str | None = None,
    parent_policy_id: str | None = None,
    rollout_percent: int = 100,
) -> SecurityThresholdPolicy:
    max_version = await db.execute(select(func.max(SecurityThresholdPolicyModel.version)))
    next_version = int(max_version.scalar_one_or_none() or 0) + 1
    row = SecurityThresholdPolicyModel(
        version=next_version,
        status=SecurityThresholdPolicyStatus.DRAFT.value,
        rollout_percent=max(0, min(100, rollout_percent)),
        config=merge_security_policy_defaults(config),
        note=note,
        created_by=created_by,
        created_at=datetime.utcnow(),
        parent_policy_id=parent_policy_id,
    )
    db.add(row)
    await db.flush()
    return _to_schema(row)


async def activate_security_threshold_policy(
    db: AsyncSession,
    *,
    policy_id: str,
) -> SecurityThresholdPolicy:
    row = await db.get(SecurityThresholdPolicyModel, policy_id)
    if row is None:
        raise ValueError("policy not found")

    now = datetime.utcnow()
    await db.execute(
        SecurityThresholdPolicyModel.__table__.update()
        .where(
            SecurityThresholdPolicyModel.status.in_(
                [SecurityThresholdPolicyStatus.ACTIVE.value, SecurityThresholdPolicyStatus.CANDIDATE.value]
            )
        )
        .values(status=SecurityThresholdPolicyStatus.ARCHIVED.value, archived_at=now)
    )
    row.status = SecurityThresholdPolicyStatus.ACTIVE.value
    row.rollout_percent = 100
    row.activated_at = now
    row.archived_at = None
    await db.flush()
    return _to_schema(row)


async def set_candidate_security_threshold_policy(
    db: AsyncSession,
    *,
    policy_id: str,
    rollout_percent: int,
) -> SecurityThresholdPolicy:
    if rollout_percent < 1 or rollout_percent > 99:
        raise ValueError("rollout_percent must be between 1 and 99 for candidate rollout")
    row = await db.get(SecurityThresholdPolicyModel, policy_id)
    if row is None:
        raise ValueError("policy not found")
    now = datetime.utcnow()
    await db.execute(
        SecurityThresholdPolicyModel.__table__.update()
        .where(SecurityThresholdPolicyModel.status == SecurityThresholdPolicyStatus.CANDIDATE.value)
        .values(status=SecurityThresholdPolicyStatus.ARCHIVED.value, archived_at=now)
    )
    row.status = SecurityThresholdPolicyStatus.CANDIDATE.value
    row.rollout_percent = rollout_percent
    row.activated_at = now
    row.archived_at = None
    await db.flush()
    return _to_schema(row)


async def rollback_security_threshold_policy(
    db: AsyncSession,
    *,
    target_policy_id: str | None = None,
) -> SecurityThresholdPolicy:
    target: SecurityThresholdPolicyModel | None = None
    if target_policy_id:
        target = await db.get(SecurityThresholdPolicyModel, target_policy_id)
    else:
        result = await db.execute(
            select(SecurityThresholdPolicyModel)
            .where(SecurityThresholdPolicyModel.status == SecurityThresholdPolicyStatus.ARCHIVED.value)
            .order_by(SecurityThresholdPolicyModel.activated_at.desc(), SecurityThresholdPolicyModel.version.desc())
            .limit(1)
        )
        target = result.scalar_one_or_none()

    if target is None:
        raise ValueError("rollback target policy not found")

    now = datetime.utcnow()
    await db.execute(
        SecurityThresholdPolicyModel.__table__.update()
        .where(
            SecurityThresholdPolicyModel.status.in_(
                [SecurityThresholdPolicyStatus.ACTIVE.value, SecurityThresholdPolicyStatus.CANDIDATE.value]
            )
        )
        .values(status=SecurityThresholdPolicyStatus.ARCHIVED.value, archived_at=now)
    )
    target.status = SecurityThresholdPolicyStatus.ACTIVE.value
    target.rollout_percent = 100
    target.activated_at = now
    target.archived_at = None
    await db.flush()
    return _to_schema(target)


def _bucket_for_actor(actor_id: str) -> int:
    digest = hashlib.sha256(actor_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


async def resolve_security_threshold_policy(
    db: AsyncSession,
    *,
    actor_id: str | None,
    explicit_policy_id: str | None = None,
) -> SecurityThresholdPolicyResolveResult:
    if explicit_policy_id:
        explicit = await db.get(SecurityThresholdPolicyModel, explicit_policy_id)
        if explicit is None:
            return SecurityThresholdPolicyResolveResult(reason="explicit_policy_not_found", actor_id=actor_id)
        return SecurityThresholdPolicyResolveResult(
            policy=_to_schema(explicit),
            matched_candidate=(explicit.status == SecurityThresholdPolicyStatus.CANDIDATE.value),
            actor_id=actor_id,
            reason="explicit_policy",
        )

    active_result = await db.execute(
        select(SecurityThresholdPolicyModel)
        .where(SecurityThresholdPolicyModel.status == SecurityThresholdPolicyStatus.ACTIVE.value)
        .order_by(SecurityThresholdPolicyModel.activated_at.desc(), SecurityThresholdPolicyModel.version.desc())
        .limit(1)
    )
    active = active_result.scalar_one_or_none()

    candidate_result = await db.execute(
        select(SecurityThresholdPolicyModel)
        .where(SecurityThresholdPolicyModel.status == SecurityThresholdPolicyStatus.CANDIDATE.value)
        .order_by(SecurityThresholdPolicyModel.activated_at.desc(), SecurityThresholdPolicyModel.version.desc())
        .limit(1)
    )
    candidate = candidate_result.scalar_one_or_none()

    if candidate and actor_id:
        bucket = _bucket_for_actor(actor_id)
        if bucket < candidate.rollout_percent:
            return SecurityThresholdPolicyResolveResult(
                policy=_to_schema(candidate),
                matched_candidate=True,
                actor_id=actor_id,
                reason="candidate_rollout_hit",
            )

    if active:
        return SecurityThresholdPolicyResolveResult(
            policy=_to_schema(active),
            matched_candidate=False,
            actor_id=actor_id,
            reason="active_policy",
        )
    if candidate:
        return SecurityThresholdPolicyResolveResult(
            policy=_to_schema(candidate),
            matched_candidate=False,
            actor_id=actor_id,
            reason="candidate_policy_fallback",
        )
    return SecurityThresholdPolicyResolveResult(actor_id=actor_id, reason="no_policy")
