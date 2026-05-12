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
    )
