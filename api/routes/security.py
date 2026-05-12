"""
Karma API — Security Operations Routes
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from core.schemas import SecurityOpsAlertReport
from services.security_monitoring import build_security_ops_alert_report

router = APIRouter()


@router.get("/ops/alerts", response_model=SecurityOpsAlertReport)
async def get_security_ops_alerts(
    window_minutes: int = Query(15, ge=1, le=24 * 60),
    failed_auth_threshold: int = Query(10, ge=1, le=100000),
    rate_limit_threshold: int = Query(30, ge=1, le=100000),
    private_runtime_error_threshold: int = Query(5, ge=1, le=100000),
    private_runtime_error_rate_threshold: float = Query(0.25, ge=0.01, le=1.0),
    private_runtime_min_requests: int = Query(10, ge=1, le=100000),
    dimension_limit: int = Query(5, ge=1, le=50),
    alert_cooldown_minutes: int = Query(10, ge=0, le=24 * 60),
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
    baseline_window_minutes: int = Query(24 * 60, ge=10, le=14 * 24 * 60),
    baseline_drift_multiplier: float = Query(2.5, ge=1.1, le=20.0),
    baseline_min_sample_count: int = Query(3, ge=1, le=100000),
    baseline_capture_interval_minutes: int = Query(10, ge=0, le=24 * 60),
) -> SecurityOpsAlertReport:
    """
    Build a windowed security alert report from recent runtime events.
    """
    return build_security_ops_alert_report(
        window_minutes=window_minutes,
        failed_auth_threshold=failed_auth_threshold,
        rate_limit_threshold=rate_limit_threshold,
        private_runtime_error_threshold=private_runtime_error_threshold,
        private_runtime_error_rate_threshold=private_runtime_error_rate_threshold,
        private_runtime_min_requests=private_runtime_min_requests,
        dimension_limit=dimension_limit,
        alert_cooldown_minutes=alert_cooldown_minutes,
        failed_auth_threshold_overrides=failed_auth_threshold_overrides,
        rate_limit_threshold_overrides=rate_limit_threshold_overrides,
        private_runtime_error_threshold_overrides=private_runtime_error_threshold_overrides,
        private_runtime_error_rate_threshold_overrides=private_runtime_error_rate_threshold_overrides,
        baseline_window_minutes=baseline_window_minutes,
        baseline_drift_multiplier=baseline_drift_multiplier,
        baseline_min_sample_count=baseline_min_sample_count,
        baseline_capture_interval_minutes=baseline_capture_interval_minutes,
    )
