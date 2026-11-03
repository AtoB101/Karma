"""Production gate: AUTH_ENFORCE_PROTECTED_ROUTES=true for the first-key flow.

The whole test-suite runs with protected-route auth off (see tests/conftest.py),
so this file explicitly turns it back on and proves the first-key endpoints still
behave correctly under production auth: challenge/claim stay public, restricted
keys stay blocked on non-allowlist routes, and the approval handshake still works.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app import app
from config.settings import settings
from db.models.orm import Base
from db.session import get_db
from services import agent_bootstrap_credentials as bc
from services import agent_first_key as fk
from services import grant_approval

DEVICE = "device-prod-000000000000"


@pytest.fixture(autouse=True)
def _prod_auth_on(monkeypatch):
    monkeypatch.setattr(settings, "auth_enforce_protected_routes", True)
    yield


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(fk, "_STORE_PATH", tmp_path / "agent_first_key.json")
    monkeypatch.setattr(bc, "_STORE_PATH", tmp_path / "agent_api_keys.json")
    monkeypatch.setattr(grant_approval, "_STORE_PATH", tmp_path / "grant_approval.json")
    fk.reset_first_keys()
    bc.reset_bootstrap_keys()
    grant_approval.reset_grant_approvals()
    yield
    fk.reset_first_keys()
    bc.reset_bootstrap_keys()
    grant_approval.reset_grant_approvals()


@pytest.mark.asyncio
async def test_first_key_gates_under_production_auth(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/prod.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        async def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        try:
            # anonymous is blocked on a protected route
            r = await client.get("/v1/console/capabilities")
            assert r.status_code == 401, r.text

            # public first-key challenge/claim stay open
            r = await client.post(
                "/v1/agents/first-key/challenge",
                json={"device_id": DEVICE, "agent_name": "生产门测试"},
            )
            assert r.status_code == 201, r.text
            challenge_id = r.json()["challenge_id"]
            challenge = r.json()["challenge"]

            r = await client.post(
                "/v1/agents/first-key/claim",
                json={"challenge_id": challenge_id, "challenge": challenge, "device_id": DEVICE},
            )
            assert r.status_code == 200, r.text
            restricted_key = r.json()["api_key"]
            headers = {"X-Karma-Api-Key": restricted_key}

            # restricted key is still denied on a protected non-allowlist route
            r = await client.get("/v1/console/capabilities", headers=headers)
            assert r.status_code in (401, 403), r.text

            # restricted key still opens the approval handshake under production auth
            r = await client.post(
                "/v1/spending-grants/approval-request",
                json={
                    "agent_name": "生产门测试",
                    "currency": "USDC",
                    "total_limit": 10,
                    "per_tx_limit": 5,
                    "purpose_scope": ["escrow"],
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text
            assert r.json().get("challenge_id")
        finally:
            await client.aclose()
            app.dependency_overrides.pop(get_db, None)
    await engine.dispose()
