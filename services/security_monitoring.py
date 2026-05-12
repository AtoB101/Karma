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
    SecurityOpsDimensionCount,
    SecurityOpsEscalationDecision,
    SecurityOpsEscalationLevel,
    SecurityOpsAlertSeverity,
    SecurityOpsAlertType,
    SecurityOpsSummary,
)

_MAX_EVENTS = 10_000
_EVENTS: deque["SecurityMonitoringEvent"] = deque(maxlen=_MAX_EVENTS)
_LOCK = Lock()
_LAST_ALERT_EMITTED_AT: dict[SecurityOpsAlertType, datetime] = {}


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
        _LAST_ALERT_EMITTED_AT.clear()


def _list_recent_events(window_minutes: int) -> list[SecurityMonitoringEvent]:
    cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
    with _LOCK:
        return [event for event in _EVENTS if event.created_at >= cutoff]


def _top_dimension_counts(
    *,
    events: list[SecurityMonitoringEvent],
    event_type: SecurityMonitoringEventType,
    metadata_key: str,
    limit: int,
    default_key: str,
) -> list[SecurityOpsDimensionCount]:
    stats: dict[str, SecurityOpsDimensionCount] = {}
    for event in events:
        if event.event_type != event_type:
            continue
        raw_value = event.metadata.get(metadata_key)
        key = str(raw_value).strip() if raw_value else default_key
        item = stats.get(key)
        if item is None:
            item = SecurityOpsDimensionCount(key=key, count=0, last_seen_at=event.created_at)
            stats[key] = item
        item.count += 1
        if item.last_seen_at is None or event.created_at > item.last_seen_at:
            item.last_seen_at = event.created_at
    return sorted(stats.values(), key=lambda item: (-item.count, item.key))[:limit]


def _should_emit_alert_now(alert_type: SecurityOpsAlertType, *, cooldown_minutes: int) -> bool:
    if cooldown_minutes <= 0:
        return True
    now = datetime.utcnow()
    with _LOCK:
        last_emitted = _LAST_ALERT_EMITTED_AT.get(alert_type)
        if last_emitted and now - last_emitted < timedelta(minutes=cooldown_minutes):
            return False
        _LAST_ALERT_EMITTED_AT[alert_type] = now
    return True


def _build_escalation_decision(
    *,
    active_alerts: list[SecurityOpsAlert],
    suppressed_alert_count: int,
) -> SecurityOpsEscalationDecision:
    if any(alert.severity == SecurityOpsAlertSeverity.CRITICAL for alert in active_alerts):
        return SecurityOpsEscalationDecision(
            level=SecurityOpsEscalationLevel.PAGE,
            reason="critical security alert triggered",
            trigger_alert_types=[alert.alert_type for alert in active_alerts],
        )
    if any(alert.severity == SecurityOpsAlertSeverity.HIGH for alert in active_alerts):
        return SecurityOpsEscalationDecision(
            level=SecurityOpsEscalationLevel.WATCH,
            reason="high-severity security alert requires active watch",
            trigger_alert_types=[alert.alert_type for alert in active_alerts],
        )
    if suppressed_alert_count > 0:
        return SecurityOpsEscalationDecision(
            level=SecurityOpsEscalationLevel.WATCH,
            reason="alerts are currently suppressed by cooldown; continue monitoring",
            trigger_alert_types=[],
        )
    if active_alerts:
        return SecurityOpsEscalationDecision(
            level=SecurityOpsEscalationLevel.WATCH,
            reason="security alert threshold exceeded",
            trigger_alert_types=[alert.alert_type for alert in active_alerts],
        )
    return SecurityOpsEscalationDecision()


def _build_recommended_actions(
    *,
    active_alerts: list[SecurityOpsAlert],
    escalation: SecurityOpsEscalationDecision,
) -> list[str]:
    actions: list[str] = []
    alert_types = {alert.alert_type for alert in active_alerts}
    if SecurityOpsAlertType.AUTH_FAILURE_SPIKE in alert_types:
        actions.append("Rotate affected API keys and investigate top auth-failure actor/path dimensions.")
    if SecurityOpsAlertType.RATE_LIMIT_SPIKE in alert_types:
        actions.append("Apply stricter endpoint-level throttles and block abusive source identities.")
    if SecurityOpsAlertType.PRIVATE_RUNTIME_ERROR_RATE in alert_types:
        actions.append("Inspect private runtime health/dependencies and enable fallback routing if needed.")
    if escalation.level == SecurityOpsEscalationLevel.PAGE:
        actions.append("Page on-call security owner and open incident channel immediately.")
    return actions


def build_security_ops_alert_report(
    *,
    window_minutes: int = 15,
    failed_auth_threshold: int = 10,
    rate_limit_threshold: int = 30,
    private_runtime_error_threshold: int = 5,
    private_runtime_error_rate_threshold: float = 0.25,
    private_runtime_min_requests: int = 10,
    dimension_limit: int = 5,
    alert_cooldown_minutes: int = 10,
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

    candidate_alerts: list[SecurityOpsAlert] = []

    if failed_auth_count >= failed_auth_threshold:
        candidate_alerts.append(
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
        candidate_alerts.append(
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
        candidate_alerts.append(
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

    alerts: list[SecurityOpsAlert] = []
    suppressed_alert_count = 0
    for alert in candidate_alerts:
        if _should_emit_alert_now(alert.alert_type, cooldown_minutes=alert_cooldown_minutes):
            alerts.append(alert)
        else:
            suppressed_alert_count += 1

    escalation = _build_escalation_decision(
        active_alerts=alerts,
        suppressed_alert_count=suppressed_alert_count,
    )
    recommended_actions = _build_recommended_actions(
        active_alerts=alerts,
        escalation=escalation,
    )

    return SecurityOpsAlertReport(
        window_minutes=window_minutes,
        summary=SecurityOpsSummary(
            failed_auth_count=failed_auth_count,
            rate_limited_count=rate_limited_count,
            private_runtime_error_count=private_runtime_error_count,
            verify_request_count=verify_request_count,
            private_runtime_error_rate=private_runtime_error_rate,
            failed_auth_by_path=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.FAILED_AUTH,
                metadata_key="path",
                limit=dimension_limit,
                default_key="unknown",
            ),
            failed_auth_by_actor=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.FAILED_AUTH,
                metadata_key="actor_id",
                limit=dimension_limit,
                default_key="anonymous",
            ),
            rate_limited_by_path=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED,
                metadata_key="path",
                limit=dimension_limit,
                default_key="unknown",
            ),
            rate_limited_by_actor=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED,
                metadata_key="actor_id",
                limit=dimension_limit,
                default_key="anonymous",
            ),
            private_runtime_error_by_path=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.PRIVATE_RUNTIME_ERROR,
                metadata_key="path",
                limit=dimension_limit,
                default_key="unknown",
            ),
        ),
        alerts=alerts,
        suppressed_alert_count=suppressed_alert_count,
        escalation=escalation,
        recommended_actions=recommended_actions,
    )
