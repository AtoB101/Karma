from __future__ import annotations

import pytest

from api.middleware.auth import validate_api_key_for_agent
from config.settings import settings
from db.models.orm import AgentModel


def test_validate_api_key_for_agent_uses_configured_secret_map():
    original_env = settings.app_env
    original_keys = settings.auth_api_keys
    try:
        settings.app_env = "production"
        settings.auth_api_keys = "agent-secure:super-secret-value-123"

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


@pytest.mark.asyncio
async def test_issue_token_requires_valid_api_key(client, db_session):
    original_env = settings.app_env
    original_keys = settings.auth_api_keys
    try:
        settings.app_env = "test"
        settings.auth_api_keys = "agent-auth:very-strong-secret-123"

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

