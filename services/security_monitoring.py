"""
Karma Security Monitoring
In-memory rolling event tracker for security operations alerting.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from threading import Lock
from typing import Any

from core.schemas import (
    SecurityOpsAlert,
    SecurityOpsAlertReport,
    SecurityOpsAlertSeverity,
    SecurityOpsAlertType,
    SecurityOpsSummary,
)

_MAX_EVENTS = 10_000
_EVENTS: deque["SecurityMonitoringEvent"] = deque(maxlen=_MAX_EVENTS)
_LOCK = Lock()


class SecurityMonitoringEventType(str, Enum):
    FAILED_AUTH = "failed_auth"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    VERIFY_REQUEST = "verify_request"
    PRIVATE_RUNTIME_ERROR = "private_runtime_error"


@dataclass
class SecurityMonitoringEvent:
    event_type: SecurityMonitoringEventType
    created_at: datetime
    metadata: dict[str, Any]


def record_security_event(
    event_type: SecurityMonitoringEventType,
    *,
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> None:
    event = SecurityMonitoringEvent(
        event_type=event_type,
        created_at=created_at or datetime.utcnow(),
        metadata=metadata or {},
    )
    with _LOCK:
        _EVENTS.append(event)


def clear_security_events() -> None:
    with _LOCK:
        _EVENTS.clear()


def _list_recent_events(window_minutes: int) -> list[SecurityMonitoringEvent]:
    cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
    with _LOCK:
        return [event for event in _EVENTS if event.created_at >= cutoff]


def build_security_ops_alert_report(
    *,
    window_minutes: int = 15,
    failed_auth_threshold: int = 10,
    rate_limit_threshold: int = 30,
    private_runtime_error_threshold: int = 5,
    private_runtime_error_rate_threshold: float = 0.25,
    private_runtime_min_requests: int = 10,
) -> SecurityOpsAlertReport:
    events = _list_recent_events(window_minutes)
    counts = Counter(event.event_type.value for event in events)

    failed_auth_count = counts.get(SecurityMonitoringEventType.FAILED_AUTH.value, 0)
    rate_limited_count = counts.get(SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED.value, 0)
    verify_request_count = counts.get(SecurityMonitoringEventType.VERIFY_REQUEST.value, 0)
    private_runtime_error_count = counts.get(SecurityMonitoringEventType.PRIVATE_RUNTIME_ERROR.value, 0)
    private_runtime_error_rate = (
        float(private_runtime_error_count) / float(verify_request_count)
        if verify_request_count > 0
        else 0.0
    )

    alerts: list[SecurityOpsAlert] = []

    if failed_auth_count >= failed_auth_threshold:
        alerts.append(
            SecurityOpsAlert(
                severity=SecurityOpsAlertSeverity.HIGH,
                alert_type=SecurityOpsAlertType.AUTH_FAILURE_SPIKE,
                message=f"authentication failures spiked to {failed_auth_count} within {window_minutes}m",
                metadata={
                    "failed_auth_count": failed_auth_count,
                    "threshold": failed_auth_threshold,
                    "window_minutes": window_minutes,
                },
            )
        )

    if rate_limited_count >= rate_limit_threshold:
        alerts.append(
            SecurityOpsAlert(
                severity=SecurityOpsAlertSeverity.MEDIUM,
                alert_type=SecurityOpsAlertType.RATE_LIMIT_SPIKE,
                message=f"rate-limit denials spiked to {rate_limited_count} within {window_minutes}m",
                metadata={
                    "rate_limited_count": rate_limited_count,
                    "threshold": rate_limit_threshold,
                    "window_minutes": window_minutes,
                },
            )
        )

    has_private_runtime_volume = verify_request_count >= private_runtime_min_requests
    if private_runtime_error_count >= private_runtime_error_threshold and has_private_runtime_volume:
        severity = (
            SecurityOpsAlertSeverity.CRITICAL
            if private_runtime_error_rate >= private_runtime_error_rate_threshold
            else SecurityOpsAlertSeverity.HIGH
        )
        alerts.append(
            SecurityOpsAlert(
                severity=severity,
                alert_type=SecurityOpsAlertType.PRIVATE_RUNTIME_ERROR_RATE,
                message=(
                    "private runtime error rate exceeded threshold: "
                    f"{private_runtime_error_count}/{verify_request_count} "
                    f"({private_runtime_error_rate:.2%}) in {window_minutes}m"
                ),
                metadata={
                    "private_runtime_error_count": private_runtime_error_count,
                    "verify_request_count": verify_request_count,
                    "error_rate": round(private_runtime_error_rate, 4),
                    "count_threshold": private_runtime_error_threshold,
                    "error_rate_threshold": private_runtime_error_rate_threshold,
                    "min_requests": private_runtime_min_requests,
                    "window_minutes": window_minutes,
                },
            )
        )

    return SecurityOpsAlertReport(
        window_minutes=window_minutes,
        summary=SecurityOpsSummary(
            failed_auth_count=failed_auth_count,
            rate_limited_count=rate_limited_count,
            private_runtime_error_count=private_runtime_error_count,
            verify_request_count=verify_request_count,
            private_runtime_error_rate=private_runtime_error_rate,
        ),
        alerts=alerts,
    )
