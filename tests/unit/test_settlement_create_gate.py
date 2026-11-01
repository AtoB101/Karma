"""Settlement create (order) spend-grant gate for buyer agents."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch

from api.app import app
from config.settings import settings
from db.models.orm import AgentModel
from db.session import get_db

AGENT = "agent-buyer-1"
SECRET = "secret-1"
API_KEY = f"karma_{AGENT}_{SECRET}"


async def _seed_agent(db) -> None:
    db.add(
        AgentModel(
            agent_id=AGENT,
            name="buyer-agent",
            role="buyer",
            public_key="pk",
            owner_identity_id="owner-1",
        )
    )
    await db.commit()


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setattr(settings, "spending_grant_enforced", True)
    monkeypatch.setattr(settings, "auth_api_keys", f"{AGENT}:{SECRET}")


@pytest.mark.asyncio
async def test_create_settlement_denies_agent_without_grant(db_session, enforce):
    await _seed_agent(db_session)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        with (
            patch("api.routes.settlement.assert_runtime_operation_allowed"),
            patch("api.routes.settlement.audit_capacity_anchor_and_maybe_trip"),
            patch("api.routes.settlement.ensure_task_contract_exists"),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.post(
                    "/v1/settlement/create",
                    json={
                        "task_id": "task-create-gate",
                        "client_agent_id": AGENT,
                        "escrow_amount": 5000.0,
                        "currency": "USD",
                    },
                    headers={"x-karma-api-key": API_KEY},
                )
                assert r.status_code == 403, r.text
                assert "spending grant denied" in r.text
    finally:
        app.dependency_overrides.clear()
