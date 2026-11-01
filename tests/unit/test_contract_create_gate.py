"""Contract create (order) spend-grant gate for buyer agents."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import app
from config.settings import settings
from db.models.orm import AgentModel
from db.session import get_db

AGENT = "agent-contract-1"
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
async def test_create_contract_requires_identity_when_enforced(db_session, enforce):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/contracts",
                json={
                    "client_agent_id": AGENT,
                    "title": "t",
                    "description": "d",
                    "expected_output_schema": {},
                    "expected_step_count": 1,
                    "escrow_amount": 5000.0,
                    "deadline_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
                },
            )
            assert r.status_code == 401, r.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_contract_denies_agent_without_grant(db_session, enforce):
    await _seed_agent(db_session)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/contracts",
                json={
                    "client_agent_id": AGENT,
                    "title": "t",
                    "description": "d",
                    "expected_output_schema": {},
                    "expected_step_count": 1,
                    "escrow_amount": 5000.0,
                    "deadline_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
                },
                headers={"x-karma-api-key": API_KEY},
            )
            assert r.status_code == 403, r.text
            assert "spending grant denied" in r.text
    finally:
        app.dependency_overrides.clear()
