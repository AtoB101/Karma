from __future__ import annotations

import pytest

from config.settings import settings
from services.security_monitoring import (
    SecurityMonitoringEventType,
    build_security_ops_alert_report,
    clear_security_events,
    record_security_event,
)


def test_build_security_ops_alert_report_detects_spikes():
    clear_security_events()
    try:
        for _ in range(4):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        for _ in range(3):
            record_security_event(
                SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        for _ in range(10):
            record_security_event(
                SecurityMonitoringEventType.VERIFY_REQUEST,
                metadata={"path": "/v1/verify", "actor_id": "agent-v", "route_group": "verification"},
            )
        for _ in range(4):
            record_security_event(
                SecurityMonitoringEventType.PRIVATE_RUNTIME_ERROR,
                metadata={"path": "/v1/verify", "actor_id": "agent-v", "route_group": "verification"},
            )

        report = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=3,
            rate_limit_threshold=3,
            private_runtime_error_threshold=3,
            private_runtime_error_rate_threshold=0.3,
            private_runtime_min_requests=5,
            dimension_limit=3,
            alert_cooldown_minutes=0,
        )
        alert_types = {item.alert_type.value for item in report.alerts}
        assert "auth_failure_spike" in alert_types
        assert "rate_limit_spike" in alert_types
        assert "private_runtime_error_rate" in alert_types
        assert report.summary.private_runtime_error_rate == pytest.approx(0.4)
        assert report.summary.failed_auth_by_path[0].key == "/v1/auth/token"
        assert report.summary.failed_auth_by_actor[0].key == "anonymous"
        assert report.summary.failed_auth_by_route_group[0].key == "auth"
        assert report.summary.private_runtime_error_by_path[0].key == "/v1/verify"
        assert report.summary.private_runtime_error_by_route_group[0].key == "verification"
        assert report.baseline.sample_count == 0
        assert report.escalation.level.value == "page"
        assert report.recommended_actions
    finally:
        clear_security_events()


def test_security_ops_alert_suppression_cooldown():
    clear_security_events()
    try:
        for _ in range(3):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        first = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=1,
            alert_cooldown_minutes=10,
        )
        second = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=1,
            alert_cooldown_minutes=10,
        )
        assert any(item.alert_type.value == "auth_failure_spike" for item in first.alerts)
        assert second.suppressed_alert_count >= 1
        assert second.escalation.level.value in {"watch", "none"}
    finally:
        clear_security_events()


def test_security_ops_threshold_overrides_support_endpoint_and_group():
    clear_security_events()
    try:
        for _ in range(3):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        report = build_security_ops_alert_report(
            window_minutes=15,
            failed_auth_threshold=100,
            failed_auth_threshold_overrides="/v1/auth/token=2,group:auth=2",
            alert_cooldown_minutes=0,
        )
        scoped = [item for item in report.alerts if item.alert_type.value == "auth_failure_spike"]
        assert scoped
        assert any(item.metadata.get("scope_type") == "path" for item in scoped)
        assert any(item.metadata.get("scope_type") == "route_group" for item in scoped)
    finally:
        clear_security_events()


def test_security_ops_baseline_drift_alert_detected():
    clear_security_events()
    try:
        for _ in range(2):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        warmup = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=9999,
            baseline_min_sample_count=1,
            baseline_drift_multiplier=1.5,
            baseline_capture_interval_minutes=0,
            alert_cooldown_minutes=0,
        )
        assert warmup.baseline.sample_count == 0

        for _ in range(8):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        drifted = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=9999,
            baseline_min_sample_count=1,
            baseline_drift_multiplier=1.5,
            baseline_capture_interval_minutes=0,
            alert_cooldown_minutes=0,
        )
        assert drifted.baseline.sample_count >= 1
        assert any(item.alert_type.value == "auth_failure_baseline_drift" for item in drifted.alerts)
    finally:
        clear_security_events()


@pytest.mark.asyncio
async def test_security_ops_alerts_endpoint_returns_report(client):
    clear_security_events()
    try:
        for _ in range(2):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        for _ in range(2):
            record_security_event(
                SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED,
                metadata={"path": "/v1/verify", "actor_id": "agent-r", "route_group": "verification"},
            )
        for _ in range(4):
            record_security_event(
                SecurityMonitoringEventType.VERIFY_REQUEST,
                metadata={"path": "/v1/verify", "actor_id": "agent-r", "route_group": "verification"},
            )
        for _ in range(2):
            record_security_event(
                SecurityMonitoringEventType.PRIVATE_RUNTIME_ERROR,
                metadata={"path": "/v1/verify", "actor_id": "agent-r", "route_group": "verification"},
            )

        response = await client.get(
            "/v1/security/ops/alerts"
            "?window_minutes=30"
            "&failed_auth_threshold=1"
            "&rate_limit_threshold=1"
            "&private_runtime_error_threshold=1"
            "&private_runtime_error_rate_threshold=0.2"
            "&private_runtime_min_requests=2"
            "&dimension_limit=5"
            "&alert_cooldown_minutes=0"
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["summary"]["failed_auth_count"] == 2
        assert payload["summary"]["rate_limited_count"] == 2
        assert payload["summary"]["private_runtime_error_count"] == 2
        assert payload["summary"]["verify_request_count"] == 4
        assert payload["summary"]["failed_auth_by_path"][0]["key"] == "/v1/auth/token"
        assert payload["summary"]["rate_limited_by_actor"][0]["key"] == "agent-r"
        assert payload["summary"]["rate_limited_by_route_group"][0]["key"] == "verification"
        assert payload["suppressed_alert_count"] == 0
        assert "baseline" in payload
        assert payload["escalation"]["level"] in {"watch", "page"}
        assert isinstance(payload["recommended_actions"], list)
        alert_types = {item["alert_type"] for item in payload["alerts"]}
        assert "auth_failure_spike" in alert_types
        assert "rate_limit_spike" in alert_types
        assert "private_runtime_error_rate" in alert_types
    finally:
        clear_security_events()


@pytest.mark.asyncio
async def test_security_ops_middleware_tracks_failed_auth(client):
    original_env = settings.app_env
    original_keys = settings.auth_api_keys
    original_enforce = settings.auth_enforce_protected_routes
    clear_security_events()
    try:
        settings.app_env = "test"
        settings.auth_api_keys = "agent-security:secret-value-123"
        settings.auth_enforce_protected_routes = True

        unauthorized = await client.post("/v1/capacity/id-security/lock", json={"amount": 10})
        assert unauthorized.status_code == 401

        report = await client.get(
            "/v1/security/ops/alerts?window_minutes=15&failed_auth_threshold=1",
            headers={"X-Karma-Api-Key": "karma_agent-security_secret-value-123"},
        )
        assert report.status_code == 200
        body = report.json()
        assert body["summary"]["failed_auth_count"] >= 1
        assert any(item["alert_type"] == "auth_failure_spike" for item in body["alerts"])
    finally:
        settings.app_env = original_env
        settings.auth_api_keys = original_keys
        settings.auth_enforce_protected_routes = original_enforce
        clear_security_events()
