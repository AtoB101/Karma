from __future__ import annotations

from datetime import datetime

import pytest

from config.settings import settings
from db.models.orm import IdentityProfileModel
from httptest import post_minimal_contract


@pytest.mark.asyncio
async def test_admin_controls_require_whitelisted_actor(client):
    original_allowlist = settings.admin_actor_ids
    original_keys = settings.auth_api_keys
    try:
        settings.auth_api_keys = "secadmin:supersecret123456"
        settings.admin_actor_ids = ""
        resp = await client.get(
            "/v1/admin/controls",
            headers={"X-Karma-Api-Key": "karma_secadmin_supersecret123456"},
        )
        assert resp.status_code == 403
    finally:
        settings.admin_actor_ids = original_allowlist
        settings.auth_api_keys = original_keys


@pytest.mark.asyncio
async def test_admin_operational_pause_blocks_new_task_path(client):
    original_allowlist = settings.admin_actor_ids
    original_keys = settings.auth_api_keys
    try:
        settings.auth_api_keys = "sec-admin:supersecret123456"
        settings.admin_actor_ids = "sec-admin"
        headers = {"X-Karma-Api-Key": "karma_sec-admin_supersecret123456"}

        pause = await client.post(
            "/v1/admin/controls/pauses",
            headers=headers,
            json={
                "pause_new_lock": False,
                "pause_new_authorization": False,
                "pause_new_task": True,
                "pause_new_settlement": False,
                "reason": "maintenance-window",
            },
        )
        assert pause.status_code == 200
        assert pause.json()["pause_new_task"] is True

        await post_minimal_contract(
            client,
            task_id="admin-pause-task-001",
            client_agent_id="buyer-001",
            escrow_amount=10.0,
            expected_step_count=1,
        )
        blocked = await client.post(
            "/v1/settlement/create",
            json={
                "task_id": "admin-pause-task-001",
                "client_agent_id": "buyer-001",
                "escrow_amount": 10.0,
                "currency": "USD",
            },
        )
        assert blocked.status_code == 503
        assert "blocked operation 'new_task'" in blocked.json()["detail"]

        unpause = await client.post(
            "/v1/admin/controls/pauses",
            headers=headers,
            json={
                "pause_new_lock": False,
                "pause_new_authorization": False,
                "pause_new_task": False,
                "pause_new_settlement": False,
                "reason": "maintenance-finished",
            },
        )
        assert unpause.status_code == 200
        assert unpause.json()["enabled"] is False
    finally:
        settings.admin_actor_ids = original_allowlist
        settings.auth_api_keys = original_keys


@pytest.mark.asyncio
async def test_admin_can_mark_identity_risk(client, db_session):
    original_allowlist = settings.admin_actor_ids
    original_keys = settings.auth_api_keys
    try:
        settings.auth_api_keys = "sec-admin:supersecret123456"
        settings.admin_actor_ids = "sec-admin"
        headers = {"X-Karma-Api-Key": "karma_sec-admin_supersecret123456"}
        db_session.add(
            IdentityProfileModel(
                identity_id="risk-id-001",
                display_id="Karma-ID-RISK1",
                legal_identity_status="unbound",
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        await db_session.flush()

        marked = await client.post(
            "/v1/admin/controls/identities/risk-id-001/risk-mark",
            headers=headers,
            json={"risk_marked": True, "reason": "abnormal graph"},
        )
        assert marked.status_code == 200
        assert marked.json()["status"] == "risk_marked"

        cleared = await client.post(
            "/v1/admin/controls/identities/risk-id-001/risk-mark",
            headers=headers,
            json={"risk_marked": False, "reason": "manual clear"},
        )
        assert cleared.status_code == 200
        assert cleared.json()["status"] == "active"
    finally:
        settings.admin_actor_ids = original_allowlist
        settings.auth_api_keys = original_keys
