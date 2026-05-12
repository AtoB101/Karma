"""
Karma Security Policy Center
Persistent policy versioning, approval workflow, canary rollout, and rollback helpers.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import (
    SecurityOpsAlertReport,
    SecurityPolicyApprovalDecision,
    SecurityPolicyChangeAction,
    SecurityPolicyChangeApproval,
    SecurityPolicyChangeRequest,
    SecurityPolicyChangeStatus,
    SecurityPolicyDryRunResult,
    SecurityPolicyDryRunSummary,
    SecurityThresholdPolicy,
    SecurityThresholdPolicyResolveResult,
    SecurityThresholdPolicyStatus,
)
from db.models.orm import (
    SecurityPolicyChangeApprovalModel,
    SecurityPolicyChangeRequestModel,
    SecurityThresholdPolicyModel,
)
from services.security_monitoring import build_security_ops_alert_report

DEFAULT_SECURITY_POLICY_CONFIG: dict[str, Any] = {
    "window_minutes": 15,
    "failed_auth_threshold": 10,
    "rate_limit_threshold": 30,
    "private_runtime_error_threshold": 5,
    "private_runtime_error_rate_threshold": 0.25,
    "private_runtime_min_requests": 10,
    "settlement_transition_denied_threshold": 5,
    "settlement_transition_denied_rate_threshold": 0.2,
    "settlement_transition_min_requests": 10,
    "dimension_limit": 5,
    "alert_cooldown_minutes": 10,
    "failed_auth_threshold_overrides": "",
    "rate_limit_threshold_overrides": "",
    "private_runtime_error_threshold_overrides": "",
    "private_runtime_error_rate_threshold_overrides": "",
    "settlement_transition_denied_threshold_overrides": "",
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


def _approval_to_schema(row: SecurityPolicyChangeApprovalModel) -> SecurityPolicyChangeApproval:
    return SecurityPolicyChangeApproval(
        approval_id=row.approval_id,
        request_id=row.request_id,
        approver_id=row.approver_id,
        decision=SecurityPolicyApprovalDecision(row.decision),
        comment=row.comment,
        created_at=row.created_at,
    )


def _dry_run_summary(current: SecurityOpsAlertReport, projected: SecurityOpsAlertReport) -> SecurityPolicyDryRunSummary:
    current_types = {item.alert_type for item in current.alerts}
    projected_types = {item.alert_type for item in projected.alerts}
    current_critical = sum(1 for item in current.alerts if item.severity.value == "critical")
    projected_critical = sum(1 for item in projected.alerts if item.severity.value == "critical")
    current_high = sum(1 for item in current.alerts if item.severity.value == "high")
    projected_high = sum(1 for item in projected.alerts if item.severity.value == "high")
    return SecurityPolicyDryRunSummary(
        current_alert_count=len(current.alerts),
        projected_alert_count=len(projected.alerts),
        delta_alert_count=len(projected.alerts) - len(current.alerts),
        current_critical_count=current_critical,
        projected_critical_count=projected_critical,
        delta_critical_count=projected_critical - current_critical,
        current_high_count=current_high,
        projected_high_count=projected_high,
        delta_high_count=projected_high - current_high,
        newly_triggered_alert_types=sorted(projected_types - current_types, key=lambda item: item.value),
        resolved_alert_types=sorted(current_types - projected_types, key=lambda item: item.value),
    )


def merge_security_policy_defaults(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_SECURITY_POLICY_CONFIG)
    if config:
        merged.update(config)
    return merged


def _build_report_from_policy_config(config: dict[str, Any]) -> SecurityOpsAlertReport:
    merged = merge_security_policy_defaults(config)
    return build_security_ops_alert_report(
        window_minutes=int(merged["window_minutes"]),
        failed_auth_threshold=int(merged["failed_auth_threshold"]),
        rate_limit_threshold=int(merged["rate_limit_threshold"]),
        private_runtime_error_threshold=int(merged["private_runtime_error_threshold"]),
        private_runtime_error_rate_threshold=float(merged["private_runtime_error_rate_threshold"]),
        private_runtime_min_requests=int(merged["private_runtime_min_requests"]),
        settlement_transition_denied_threshold=int(merged["settlement_transition_denied_threshold"]),
        settlement_transition_denied_rate_threshold=float(merged["settlement_transition_denied_rate_threshold"]),
        settlement_transition_min_requests=int(merged["settlement_transition_min_requests"]),
        dimension_limit=int(merged["dimension_limit"]),
        alert_cooldown_minutes=0,
        failed_auth_threshold_overrides=str(merged["failed_auth_threshold_overrides"]),
        rate_limit_threshold_overrides=str(merged["rate_limit_threshold_overrides"]),
        private_runtime_error_threshold_overrides=str(merged["private_runtime_error_threshold_overrides"]),
        private_runtime_error_rate_threshold_overrides=str(merged["private_runtime_error_rate_threshold_overrides"]),
        settlement_transition_denied_threshold_overrides=str(merged["settlement_transition_denied_threshold_overrides"]),
        baseline_window_minutes=int(merged["baseline_window_minutes"]),
        baseline_drift_multiplier=float(merged["baseline_drift_multiplier"]),
        baseline_min_sample_count=int(merged["baseline_min_sample_count"]),
        baseline_capture_interval_minutes=int(merged["baseline_capture_interval_minutes"]),
        record_baseline_snapshot=False,
    )


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


async def simulate_policy_change_dry_run(
    db: AsyncSession,
    *,
    action: SecurityPolicyChangeAction,
    target_policy_id: str | None,
    target_rollback_policy_id: str | None,
    rollout_percent: int | None,
    actor_id: str | None,
) -> SecurityPolicyDryRunResult:
    current_resolved = await resolve_security_threshold_policy(db=db, actor_id=actor_id)
    current_config = merge_security_policy_defaults(current_resolved.policy.config if current_resolved.policy else None)
    current_report = _build_report_from_policy_config(current_config)

    projected_policy: SecurityThresholdPolicy | None = None
    if action in {SecurityPolicyChangeAction.ACTIVATE, SecurityPolicyChangeAction.SET_CANDIDATE}:
        if not target_policy_id:
            raise ValueError("target_policy_id is required for this action")
        if action == SecurityPolicyChangeAction.SET_CANDIDATE and rollout_percent is None:
            raise ValueError("rollout_percent is required for candidate action")
        projected_policy = await get_security_threshold_policy(db=db, policy_id=target_policy_id)
        if projected_policy is None:
            raise ValueError("target policy not found")
    elif action == SecurityPolicyChangeAction.ROLLBACK:
        if target_rollback_policy_id:
            projected_policy = await get_security_threshold_policy(db=db, policy_id=target_rollback_policy_id)
            if projected_policy is None:
                raise ValueError("rollback target policy not found")
        else:
            archived_result = await db.execute(
                select(SecurityThresholdPolicyModel)
                .where(SecurityThresholdPolicyModel.status == SecurityThresholdPolicyStatus.ARCHIVED.value)
                .order_by(SecurityThresholdPolicyModel.activated_at.desc(), SecurityThresholdPolicyModel.version.desc())
                .limit(1)
            )
            archived = archived_result.scalar_one_or_none()
            projected_policy = _to_schema(archived) if archived else None

    projected_config = merge_security_policy_defaults(projected_policy.config if projected_policy else current_config)
    projected_report = _build_report_from_policy_config(projected_config)
    if action == SecurityPolicyChangeAction.SET_CANDIDATE and rollout_percent is not None:
        projected_report = projected_report.model_copy(
            update={
                "matched_candidate": bool(actor_id and _bucket_for_actor(actor_id) < rollout_percent),
            }
        )

    return SecurityPolicyDryRunResult(
        actor_id=actor_id,
        current_policy_id=current_resolved.policy.policy_id if current_resolved.policy else None,
        projected_policy_id=projected_policy.policy_id if projected_policy else current_resolved.policy.policy_id if current_resolved.policy else None,
        current_report=current_report,
        projected_report=projected_report,
        summary=_dry_run_summary(current_report, projected_report),
    )


async def create_security_policy_change_request(
    db: AsyncSession,
    *,
    action: SecurityPolicyChangeAction,
    target_policy_id: str | None = None,
    target_rollback_policy_id: str | None = None,
    rollout_percent: int | None = None,
    note: str | None = None,
    requested_by: str | None = None,
    required_approvals: int = 2,
    dry_run_actor_id: str | None = None,
) -> SecurityPolicyChangeRequest:
    dry_run = await simulate_policy_change_dry_run(
        db=db,
        action=action,
        target_policy_id=target_policy_id,
        target_rollback_policy_id=target_rollback_policy_id,
        rollout_percent=rollout_percent,
        actor_id=dry_run_actor_id,
    )
    row = SecurityPolicyChangeRequestModel(
        action=action.value,
        status=SecurityPolicyChangeStatus.PENDING.value,
        target_policy_id=target_policy_id,
        target_rollback_policy_id=target_rollback_policy_id,
        rollout_percent=rollout_percent,
        note=note,
        requested_by=requested_by,
        requested_at=datetime.utcnow(),
        required_approvals=max(1, required_approvals),
        dry_run_report=dry_run.model_dump(mode="json"),
    )
    db.add(row)
    await db.flush()
    return await get_security_policy_change_request(db=db, request_id=row.request_id, include_approvals=True)


async def list_security_policy_change_requests(
    db: AsyncSession,
    *,
    status: SecurityPolicyChangeStatus | None = None,
    limit: int = 50,
) -> list[SecurityPolicyChangeRequest]:
    stmt = select(SecurityPolicyChangeRequestModel).order_by(SecurityPolicyChangeRequestModel.requested_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(SecurityPolicyChangeRequestModel.status == status.value)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    items: list[SecurityPolicyChangeRequest] = []
    for row in rows:
        items.append(await get_security_policy_change_request(db=db, request_id=row.request_id, include_approvals=True))
    return items


async def get_security_policy_change_request(
    db: AsyncSession,
    *,
    request_id: str,
    include_approvals: bool = True,
) -> SecurityPolicyChangeRequest:
    row = await db.get(SecurityPolicyChangeRequestModel, request_id)
    if row is None:
        raise ValueError("change request not found")
    approvals: list[SecurityPolicyChangeApproval] = []
    if include_approvals:
        result = await db.execute(
            select(SecurityPolicyChangeApprovalModel)
            .where(SecurityPolicyChangeApprovalModel.request_id == request_id)
            .order_by(SecurityPolicyChangeApprovalModel.created_at.asc())
        )
        approvals = [_approval_to_schema(item) for item in result.scalars().all()]
    dry_run = SecurityPolicyDryRunResult(**row.dry_run_report) if row.dry_run_report else None
    return SecurityPolicyChangeRequest(
        request_id=row.request_id,
        action=SecurityPolicyChangeAction(row.action),
        status=SecurityPolicyChangeStatus(row.status),
        target_policy_id=row.target_policy_id,
        target_rollback_policy_id=row.target_rollback_policy_id,
        rollout_percent=row.rollout_percent,
        note=row.note,
        requested_by=row.requested_by,
        requested_at=row.requested_at,
        applied_at=row.applied_at,
        required_approvals=row.required_approvals,
        approvals=approvals,
        dry_run=dry_run,
    )


async def review_security_policy_change_request(
    db: AsyncSession,
    *,
    request_id: str,
    approver_id: str,
    decision: SecurityPolicyApprovalDecision,
    comment: str | None = None,
) -> SecurityPolicyChangeRequest:
    row = await db.get(SecurityPolicyChangeRequestModel, request_id)
    if row is None:
        raise ValueError("change request not found")
    if row.status in {SecurityPolicyChangeStatus.APPLIED.value, SecurityPolicyChangeStatus.CANCELLED.value}:
        raise ValueError("change request can no longer be reviewed")

    existing_result = await db.execute(
        select(SecurityPolicyChangeApprovalModel).where(
            SecurityPolicyChangeApprovalModel.request_id == request_id,
            SecurityPolicyChangeApprovalModel.approver_id == approver_id,
        )
    )
    approval = existing_result.scalar_one_or_none()
    now = datetime.utcnow()
    if approval is None:
        approval = SecurityPolicyChangeApprovalModel(
            request_id=request_id,
            approver_id=approver_id,
            decision=decision.value,
            comment=comment,
            created_at=now,
        )
        db.add(approval)
    else:
        approval.decision = decision.value
        approval.comment = comment
        approval.created_at = now
    await db.flush()

    approvals_result = await db.execute(
        select(SecurityPolicyChangeApprovalModel).where(SecurityPolicyChangeApprovalModel.request_id == request_id)
    )
    approvals = approvals_result.scalars().all()
    approved_count = sum(1 for item in approvals if item.decision == SecurityPolicyApprovalDecision.APPROVE.value)
    rejected_count = sum(1 for item in approvals if item.decision == SecurityPolicyApprovalDecision.REJECT.value)

    if rejected_count > 0:
        row.status = SecurityPolicyChangeStatus.REJECTED.value
    elif approved_count >= row.required_approvals:
        row.status = SecurityPolicyChangeStatus.APPROVED.value
    else:
        row.status = SecurityPolicyChangeStatus.PENDING.value
    await db.flush()
    return await get_security_policy_change_request(db=db, request_id=request_id, include_approvals=True)


async def apply_security_policy_change_request(
    db: AsyncSession,
    *,
    request_id: str,
) -> tuple[SecurityPolicyChangeRequest, SecurityThresholdPolicy]:
    row = await db.get(SecurityPolicyChangeRequestModel, request_id)
    if row is None:
        raise ValueError("change request not found")
    if row.status != SecurityPolicyChangeStatus.APPROVED.value:
        raise ValueError("change request must be approved before apply")

    if row.action == SecurityPolicyChangeAction.ACTIVATE.value:
        if not row.target_policy_id:
            raise ValueError("activate request missing target policy")
        policy = await activate_security_threshold_policy(db=db, policy_id=row.target_policy_id)
    elif row.action == SecurityPolicyChangeAction.SET_CANDIDATE.value:
        if not row.target_policy_id:
            raise ValueError("candidate request missing target policy")
        policy = await set_candidate_security_threshold_policy(
            db=db,
            policy_id=row.target_policy_id,
            rollout_percent=row.rollout_percent or 10,
        )
    elif row.action == SecurityPolicyChangeAction.ROLLBACK.value:
        policy = await rollback_security_threshold_policy(
            db=db,
            target_policy_id=row.target_rollback_policy_id,
        )
    else:
        raise ValueError("unsupported change action")

    row.status = SecurityPolicyChangeStatus.APPLIED.value
    row.applied_at = datetime.utcnow()
    await db.flush()
    return (
        await get_security_policy_change_request(db=db, request_id=request_id, include_approvals=True),
        policy,
    )
