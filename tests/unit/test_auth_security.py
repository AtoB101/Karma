from __future__ import annotations

import pytest

from api.middleware.auth import resolve_agent_id_from_auth_headers, validate_api_key_for_agent
from config.settings import settings
from db.models.orm import AgentModel


def test_validate_api_key_for_agent_uses_configured_secret_map():
    original_env = settings.app_env
    original_keys = settings.auth_api_keys
    original_enforce = settings.auth_enforce_protected_routes
    try:
        settings.app_env = "production"
        settings.auth_api_keys = "agent-secure:super-secret-value-123"
        settings.auth_enforce_protected_routes = True

        assert validate_api_key_for_agent(
            "agent-secure",
            "karma_agent-secure_super-secret-value-123",
        )
        assert not validate_api_key_for_agent(
            "agent-secure",
            "karma_agent-secure_wrong-secret",
        )
        assert not validate_api_key_for_agent(
            "other-agent",
            "karma_agent-secure_super-secret-value-123",
        )

        settings.auth_api_keys = ""
        assert not validate_api_key_for_agent(
            "agent-secure",
            "karma_agent-secure_super-secret-value-123",
        )
    finally:
        settings.app_env = original_env
        settings.auth_api_keys = original_keys
        settings.auth_enforce_protected_routes = original_enforce


def test_resolve_agent_id_from_headers_prefers_bearer_then_api_key():
    original_env = settings.app_env
    original_keys = settings.auth_api_keys
    original_enforce = settings.auth_enforce_protected_routes
    try:
        settings.app_env = "test"
        settings.auth_api_keys = "agent-secure:super-secret-value-123"
        settings.auth_enforce_protected_routes = True

        assert (
            resolve_agent_id_from_auth_headers(
                authorization=None,
                api_key="karma_agent-secure_super-secret-value-123",
            )
            == "agent-secure"
        )
        assert (
            resolve_agent_id_from_auth_headers(
                authorization=None,
                api_key="karma_agent-secure_bad",
            )
            is None
        )
    finally:
        settings.app_env = original_env
        settings.auth_api_keys = original_keys
        settings.auth_enforce_protected_routes = original_enforce


@pytest.mark.asyncio
async def test_issue_token_requires_valid_api_key(client, db_session):
    original_env = settings.app_env
    original_keys = settings.auth_api_keys
    original_enforce = settings.auth_enforce_protected_routes
    try:
        settings.app_env = "test"
        settings.auth_api_keys = "agent-auth:very-strong-secret-123"
        settings.auth_enforce_protected_routes = False

        db_session.add(
            AgentModel(
                agent_id="agent-auth",
                name="Auth Agent",
                role="worker",
                public_key="test-public-key",
                is_active=True,
            )
        )
        await db_session.flush()

        invalid = await client.post(
            "/v1/auth/token",
            json={"agent_id": "agent-auth", "api_key": "karma_agent-auth_wrong"},
        )
        assert invalid.status_code == 401

        valid = await client.post(
            "/v1/auth/token",
            json={
                "agent_id": "agent-auth",
                "api_key": "karma_agent-auth_very-strong-secret-123",
            },
        )
        assert valid.status_code == 200
        payload = valid.json()
        assert payload["agent_id"] == "agent-auth"
        assert payload["access_token"]
    finally:
        settings.app_env = original_env
        settings.auth_api_keys = original_keys
        settings.auth_enforce_protected_routes = original_enforce


@pytest.mark.asyncio
async def test_protected_routes_require_auth_when_enforced(client):
    original_env = settings.app_env
    original_keys = settings.auth_api_keys
    original_enforce = settings.auth_enforce_protected_routes
    try:
        settings.app_env = "test"
        settings.auth_api_keys = "agent-capacity:capacity-secret-123"
        settings.auth_enforce_protected_routes = True

        unauthorized = await client.post("/v1/capacity/agent-capacity/lock", json={"amount": 10})
        assert unauthorized.status_code == 401

        authorized = await client.post(
            "/v1/capacity/agent-capacity/lock",
            json={"amount": 10},
            headers={"X-Karma-Api-Key": "karma_agent-capacity_capacity-secret-123"},
        )
        assert authorized.status_code == 200
    finally:
        settings.app_env = original_env
        settings.auth_api_keys = original_keys
        settings.auth_enforce_protected_routes = original_enforce


def test_resolve_verify_submitter_id_allows_anonymous_when_enforcement_off():
    from starlette.requests import Request

    async def recv():
        return {"type": "http.disconnect"}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/verify",
        "raw_path": b"/v1/verify",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("test", 80),
    }
    req = Request(scope, recv)
    orig = settings.auth_enforce_protected_routes
    try:
        settings.auth_enforce_protected_routes = False
        from api.middleware.auth import resolve_verify_submitter_id

        assert resolve_verify_submitter_id(req) == "anonymous-verify"
    finally:
        settings.auth_enforce_protected_routes = orig


def test_resolve_verify_submitter_id_requires_auth_when_enforcement_on():
    from starlette.requests import Request
    from fastapi import HTTPException

    async def recv():
        return {"type": "http.disconnect"}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/verify",
        "raw_path": b"/v1/verify",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("test", 80),
    }
    req = Request(scope, recv)
    orig = settings.auth_enforce_protected_routes
    try:
        settings.auth_enforce_protected_routes = True
        from api.middleware.auth import resolve_verify_submitter_id

        with pytest.raises(HTTPException) as ei:
            resolve_verify_submitter_id(req)
        assert ei.value.status_code == 401
    finally:
        settings.auth_enforce_protected_routes = orig

