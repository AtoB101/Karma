from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.middleware import rate_limit as rate_limit_module
from config.settings import settings
from services.runtime_safety import get_runtime_safety_mode_state, set_runtime_safety_mode
from services.security_monitoring import clear_security_events


def _build_request(
    *,
    path: str = "/v1/security/ops/alerts",
    method: str = "GET",
    headers: dict[str, str] | None = None,
    client_host: str = "198.51.100.20",
) -> Request:
    raw_headers: list[tuple[bytes, bytes]] = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("utf-8"), value.encode("utf-8")))

    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "headers": raw_headers,
        "client": (client_host, 12345),
        "scheme": "http",
        "server": ("test", 80),
    }

    async def _receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, _receive)


@pytest.mark.asyncio
async def test_ops_drill_rate_limit_fail_modes(monkeypatch: pytest.MonkeyPatch):
    async def _boom_get_redis():
        raise RuntimeError("redis unavailable in drill")

    monkeypatch.setattr(rate_limit_module, "get_redis", _boom_get_redis)

    original_env = settings.app_env
    original_fail_closed = settings.rate_limit_fail_closed_keys
    try:
        settings.rate_limit_fail_closed_keys = "state_transition,write_sensitive"
        request = _build_request(
            headers={"X-Karma-Api-Key": "karma_ops-drill-secret_redis-chaos-token"}
        )

        settings.app_env = "production"
        await rate_limit_module.rate_limit(request, "default")
        with pytest.raises(HTTPException) as exc:
            await rate_limit_module.rate_limit(request, "state_transition")
        assert exc.value.status_code == 503
        assert "Rate limiter unavailable" in exc.value.detail

        settings.app_env = "development"
        await rate_limit_module.rate_limit(request, "state_transition")
    finally:
        settings.app_env = original_env
        settings.rate_limit_fail_closed_keys = original_fail_closed


@pytest.mark.asyncio
async def test_ops_drill_transition_flood_emits_critical_denied_rate_alert(client):
    clear_security_events()
    set_runtime_safety_mode(enabled=False, reason="drill setup", actor_id="ops-drill")
    try:
        task_id = "task-ops-drill-flood-001"
        headers = {"X-Karma-Api-Key": "karma_flood-runner_supersecret123"}
        created = await client.post(
            "/v1/settlement/create",
            json={
                "task_id": task_id,
                "client_agent_id": "buyer-ops-001",
                "escrow_amount": 12.0,
                "currency": "USD",
            },
            headers=headers,
        )
        assert created.status_code == 201

        denied_count = 0
        for _ in range(12):
            denied = await client.post(f"/v1/settlement/{task_id}/submit", json={}, headers=headers)
            assert denied.status_code == 409
            denied_count += 1
        assert denied_count == 12

        report = await client.get(
            "/v1/security/ops/alerts"
            "?window_minutes=30"
            "&settlement_transition_denied_threshold=3"
            "&settlement_transition_denied_rate_threshold=0.5"
            "&settlement_transition_min_requests=5"
            "&alert_cooldown_minutes=0"
            "&auto_brake_on_transition_critical=false",
            headers=headers,
        )
        assert report.status_code == 200
        payload = report.json()
        assert payload["summary"]["settlement_transition_denied_count"] >= 12
        assert payload["summary"]["settlement_transition_denied_rate"] >= 0.8
        alert_types = {item["alert_type"] for item in payload["alerts"]}
        assert "settlement_transition_denied_spike" in alert_types
        assert "settlement_transition_denied_rate" in alert_types
        assert any(
            item["key"] == "flood-runner"
            for item in payload["summary"]["settlement_transition_denied_by_actor"]
        )
    finally:
        clear_security_events()
        set_runtime_safety_mode(enabled=False, reason="drill cleanup", actor_id="ops-drill")


@pytest.mark.asyncio
async def test_ops_drill_auto_brake_false_positive_is_blocked(client):
    clear_security_events()
    set_runtime_safety_mode(enabled=False, reason="drill setup", actor_id="ops-drill")
    original_admin_ids = settings.admin_actor_ids
    try:
        settings.admin_actor_ids = "sec-admin"
        headers = {"X-Karma-Api-Key": "karma_sec-admin_supersecret123"}
        task_id = "task-ops-drill-fp-001"

        created = await client.post(
            "/v1/settlement/create",
            json={
                "task_id": task_id,
                "client_agent_id": "buyer-ops-002",
                "escrow_amount": 10.0,
                "currency": "USD",
            },
            headers=headers,
        )
        assert created.status_code == 201

        denied = await client.post(f"/v1/settlement/{task_id}/submit", json={}, headers=headers)
        assert denied.status_code == 409

        assert (await client.post(f"/v1/settlement/{task_id}/pending", json={}, headers=headers)).status_code == 200
        assert (
            await client.post(
                f"/v1/settlement/{task_id}/lock",
                json={"worker_agent_id": "worker-ops-002"},
                headers=headers,
            )
        ).status_code == 200
        assert (await client.post(f"/v1/settlement/{task_id}/start", json={}, headers=headers)).status_code == 200
        assert (await client.post(f"/v1/settlement/{task_id}/submit", json={}, headers=headers)).status_code == 200

        report = await client.get(
            "/v1/security/ops/alerts"
            "?window_minutes=30"
            "&settlement_transition_denied_threshold=50"
            "&settlement_transition_denied_rate_threshold=0.5"
            "&settlement_transition_min_requests=5"
            "&alert_cooldown_minutes=0"
            "&auto_brake_on_transition_critical=true"
            "&auto_brake_actor_id=sec-auto",
            headers=headers,
        )
        assert report.status_code == 200
        state = get_runtime_safety_mode_state()
        assert state.enabled is False
    finally:
        settings.admin_actor_ids = original_admin_ids
        clear_security_events()
        set_runtime_safety_mode(enabled=False, reason="drill cleanup", actor_id="ops-drill")


@pytest.mark.asyncio
async def test_ops_drill_auto_brake_false_negative_control_path(client):
    clear_security_events()
    set_runtime_safety_mode(enabled=False, reason="drill setup", actor_id="ops-drill")
    original_admin_ids = settings.admin_actor_ids
    try:
        settings.admin_actor_ids = "sec-admin"
        headers = {"X-Karma-Api-Key": "karma_sec-admin_supersecret123"}
        task_id = "task-ops-drill-fn-001"

        created = await client.post(
            "/v1/settlement/create",
            json={
                "task_id": task_id,
                "client_agent_id": "buyer-ops-003",
                "escrow_amount": 11.0,
                "currency": "USD",
            },
            headers=headers,
        )
        assert created.status_code == 201

        for _ in range(8):
            denied = await client.post(f"/v1/settlement/{task_id}/submit", json={}, headers=headers)
            assert denied.status_code == 409

        report = await client.get(
            "/v1/security/ops/alerts"
            "?window_minutes=30"
            "&settlement_transition_denied_threshold=1"
            "&settlement_transition_denied_rate_threshold=0.4"
            "&settlement_transition_min_requests=2"
            "&alert_cooldown_minutes=0"
            "&auto_brake_on_transition_critical=false",
            headers=headers,
        )
        assert report.status_code == 200
        alert_types = {item["alert_type"] for item in report.json()["alerts"]}
        assert "settlement_transition_denied_rate" in alert_types
        state = get_runtime_safety_mode_state()
        assert state.enabled is False
    finally:
        settings.admin_actor_ids = original_admin_ids
        clear_security_events()
        set_runtime_safety_mode(enabled=False, reason="drill cleanup", actor_id="ops-drill")
