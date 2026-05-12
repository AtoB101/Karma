"""
Karma API — Security Operations Routes
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import (
    SecurityOpsAlertReport,
    SecurityThresholdPolicy,
    SecurityThresholdPolicyStatus,
)
from db.session import get_db
from services.security_monitoring import build_security_ops_alert_report
from services.security_policy_center import (
    create_security_threshold_policy,
    activate_security_threshold_policy,
    list_security_threshold_policies,
    get_security_threshold_policy,
    merge_security_policy_defaults,
    resolve_security_threshold_policy,
    rollback_security_threshold_policy,
    set_candidate_security_threshold_policy,
)

router = APIRouter()


class CreateSecurityThresholdPolicyRequest(BaseModel):
    config: dict[str, object] = Field(default_factory=dict)
    note: str | None = None
    created_by: str | None = None
    parent_policy_id: str | None = None
    rollout_percent: int = Field(default=100, ge=0, le=100)


class SetSecurityThresholdPolicyCandidateRequest(BaseModel):
    rollout_percent: int = Field(default=10, ge=1, le=99)


class RollbackSecurityThresholdPolicyRequest(BaseModel):
    target_policy_id: str | None = None


@router.post("/policies", response_model=SecurityThresholdPolicy, status_code=201)
async def create_security_policy(
    body: CreateSecurityThresholdPolicyRequest,
    db: AsyncSession = Depends(get_db),
) -> SecurityThresholdPolicy:
    return await create_security_threshold_policy(
        db=db,
        config=body.config,
        note=body.note,
        created_by=body.created_by,
        parent_policy_id=body.parent_policy_id,
        rollout_percent=body.rollout_percent,
    )


@router.get("/policies", response_model=list[SecurityThresholdPolicy])
async def list_security_policies(
    status: SecurityThresholdPolicyStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[SecurityThresholdPolicy]:
    return await list_security_threshold_policies(db=db, status=status, limit=limit)


@router.get("/policies/{policy_id}", response_model=SecurityThresholdPolicy)
async def get_security_policy(
    policy_id: str,
    db: AsyncSession = Depends(get_db),
) -> SecurityThresholdPolicy:
    policy = await get_security_threshold_policy(db=db, policy_id=policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="security threshold policy not found")
    return policy


@router.post("/policies/{policy_id}/activate", response_model=SecurityThresholdPolicy)
async def activate_security_policy(
    policy_id: str,
    db: AsyncSession = Depends(get_db),
) -> SecurityThresholdPolicy:
    try:
        return await activate_security_threshold_policy(db=db, policy_id=policy_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/policies/{policy_id}/candidate", response_model=SecurityThresholdPolicy)
async def set_security_policy_candidate(
    policy_id: str,
    body: SetSecurityThresholdPolicyCandidateRequest,
    db: AsyncSession = Depends(get_db),
) -> SecurityThresholdPolicy:
    try:
        return await set_candidate_security_threshold_policy(
            db=db,
            policy_id=policy_id,
            rollout_percent=body.rollout_percent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/policies/rollback", response_model=SecurityThresholdPolicy)
async def rollback_security_policy(
    body: RollbackSecurityThresholdPolicyRequest,
    db: AsyncSession = Depends(get_db),
) -> SecurityThresholdPolicy:
    try:
        return await rollback_security_threshold_policy(
            db=db,
            target_policy_id=body.target_policy_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/ops/alerts", response_model=SecurityOpsAlertReport)
async def get_security_ops_alerts(
    window_minutes: int | None = Query(default=None, ge=1, le=24 * 60),
    failed_auth_threshold: int | None = Query(default=None, ge=1, le=100000),
    rate_limit_threshold: int | None = Query(default=None, ge=1, le=100000),
    private_runtime_error_threshold: int | None = Query(default=None, ge=1, le=100000),
    private_runtime_error_rate_threshold: float | None = Query(default=None, ge=0.01, le=1.0),
    private_runtime_min_requests: int | None = Query(default=None, ge=1, le=100000),
    dimension_limit: int | None = Query(default=None, ge=1, le=50),
    alert_cooldown_minutes: int | None = Query(default=None, ge=0, le=24 * 60),
    failed_auth_threshold_overrides: str | None = Query(
        None,
        description="Comma-separated overrides: '/v1/auth/token=5,group:auth=8'",
    ),
    rate_limit_threshold_overrides: str | None = Query(
        None,
        description="Comma-separated overrides: '/v1/verify=20,group:verification=25'",
    ),
    private_runtime_error_threshold_overrides: str | None = Query(
        None,
        description="Comma-separated overrides: '/v1/verify=3,group:verification=4'",
    ),
    private_runtime_error_rate_threshold_overrides: str | None = Query(
        None,
        description="Comma-separated overrides: '/v1/verify=0.2,group:verification=0.3'",
    ),
    baseline_window_minutes: int | None = Query(default=None, ge=10, le=14 * 24 * 60),
    baseline_drift_multiplier: float | None = Query(default=None, ge=1.1, le=20.0),
    baseline_min_sample_count: int | None = Query(default=None, ge=1, le=100000),
    baseline_capture_interval_minutes: int | None = Query(default=None, ge=0, le=24 * 60),
    apply_policy_center: bool = Query(default=True),
    policy_id: str | None = Query(default=None),
    policy_actor_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> SecurityOpsAlertReport:
    """
    Build a windowed security alert report from recent runtime events.
    """
    resolved = await resolve_security_threshold_policy(
        db=db,
        actor_id=policy_actor_id,
        explicit_policy_id=policy_id if apply_policy_center else None,
    )
    if apply_policy_center and policy_id and resolved.policy is None:
        raise HTTPException(status_code=404, detail="security threshold policy not found")
    policy_config = merge_security_policy_defaults(
        resolved.policy.config if (apply_policy_center and resolved.policy) else None
    )
    report = build_security_ops_alert_report(
        window_minutes=window_minutes if window_minutes is not None else int(policy_config["window_minutes"]),
        failed_auth_threshold=(
            failed_auth_threshold
            if failed_auth_threshold is not None
            else int(policy_config["failed_auth_threshold"])
        ),
        rate_limit_threshold=(
            rate_limit_threshold
            if rate_limit_threshold is not None
            else int(policy_config["rate_limit_threshold"])
        ),
        private_runtime_error_threshold=(
            private_runtime_error_threshold
            if private_runtime_error_threshold is not None
            else int(policy_config["private_runtime_error_threshold"])
        ),
        private_runtime_error_rate_threshold=(
            private_runtime_error_rate_threshold
            if private_runtime_error_rate_threshold is not None
            else float(policy_config["private_runtime_error_rate_threshold"])
        ),
        private_runtime_min_requests=(
            private_runtime_min_requests
            if private_runtime_min_requests is not None
            else int(policy_config["private_runtime_min_requests"])
        ),
        dimension_limit=dimension_limit if dimension_limit is not None else int(policy_config["dimension_limit"]),
        alert_cooldown_minutes=(
            alert_cooldown_minutes
            if alert_cooldown_minutes is not None
            else int(policy_config["alert_cooldown_minutes"])
        ),
        failed_auth_threshold_overrides=(
            failed_auth_threshold_overrides
            if failed_auth_threshold_overrides is not None
            else str(policy_config["failed_auth_threshold_overrides"])
        ),
        rate_limit_threshold_overrides=(
            rate_limit_threshold_overrides
            if rate_limit_threshold_overrides is not None
            else str(policy_config["rate_limit_threshold_overrides"])
        ),
        private_runtime_error_threshold_overrides=(
            private_runtime_error_threshold_overrides
            if private_runtime_error_threshold_overrides is not None
            else str(policy_config["private_runtime_error_threshold_overrides"])
        ),
        private_runtime_error_rate_threshold_overrides=(
            private_runtime_error_rate_threshold_overrides
            if private_runtime_error_rate_threshold_overrides is not None
            else str(policy_config["private_runtime_error_rate_threshold_overrides"])
        ),
        baseline_window_minutes=(
            baseline_window_minutes
            if baseline_window_minutes is not None
            else int(policy_config["baseline_window_minutes"])
        ),
        baseline_drift_multiplier=(
            baseline_drift_multiplier
            if baseline_drift_multiplier is not None
            else float(policy_config["baseline_drift_multiplier"])
        ),
        baseline_min_sample_count=(
            baseline_min_sample_count
            if baseline_min_sample_count is not None
            else int(policy_config["baseline_min_sample_count"])
        ),
        baseline_capture_interval_minutes=(
            baseline_capture_interval_minutes
            if baseline_capture_interval_minutes is not None
            else int(policy_config["baseline_capture_interval_minutes"])
        ),
    )
    if apply_policy_center and resolved.policy is not None:
        report = report.model_copy(
            update={
                "policy_id": resolved.policy.policy_id,
                "policy_version": resolved.policy.version,
                "policy_status": resolved.policy.status,
                "matched_candidate": resolved.matched_candidate,
            }
        )
    return report
