"""Owner-console agent connect: identity card holder binds an agent.

Covers the production gates that a browser alone cannot satisfy on
``/one-click-connect``: proof-of-possession over the connect challenge and an
owner-signed responsibility ack. Karma custody-holds the agent's operational
Ed25519 key, so both are produced server-side while the owner stays wallet-only.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app import app
from api.middleware.auth import validate_api_key_for_agent
from db.models.orm import Base
from db.session import get_db
from services.agent_bootstrap_credentials import has_minted_api_key, reset_bootstrap_keys
from services.agent_key_store import has_agent_key, load_agent_signer
from services.agent_onboarding_template import (
    get_industry,
    load_onboarding_catalog,
    validate_service_specs_for_industries,
)
from services.agent_profile_store import clear_profile_cards

OWNER = "kid_ownerconsole0001"
OTHER = "kid_someoneelse00002"


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/oc.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("KARMA_AGENT_KEY_DIR", str(tmp_path / "agent_keys"))
    reset_bootstrap_keys()
    clear_profile_cards()
    load_onboarding_catalog.cache_clear()
    yield
    reset_bootstrap_keys()
    clear_profile_cards()
    load_onboarding_catalog.cache_clear()


def _food_specs() -> dict:
    spec = dict(get_industry("food_delivery")["example_service_spec"])
    # The catalog example must itself satisfy the hard-metric contract.
    assert validate_service_specs_for_industries(["food_delivery"], {"food_delivery": spec}) == []
    return {"food_delivery": spec}


def _payload(**over):
    body = {
        "side": "seller",
        "vertical": "food",
        "display_name": "Owner Food Agent",
        "owner_identity_id": OWNER,
        "answers": {
            "industry_ids": ["food_delivery"],
            "service_specs": _food_specs(),
        },
    }
    body.update(over)
    return body


@pytest.mark.asyncio
async def test_owner_connect_requires_authentication(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/v1/agents/owner-connect", json=_payload())
            assert r.status_code == 403, r.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_owner_connect_rejects_foreign_owner(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/v1/agents/owner-connect",
                json=_payload(owner_identity_id=OTHER),
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert r.status_code == 403, r.text
            assert "authenticated identity" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_owner_connect_passes_production_gates(db_session, monkeypatch):
    """With the prod gates ON (real service_specs + PoP + owner-signed ack)."""
    monkeypatch.setattr("api.routes.agents.is_prod_like_env", lambda: True)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/v1/agents/owner-connect",
                json=_payload(),
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["schema_version"] == "karma-agent-owner-connect-v1"
            assert body["profile_id"] == "merchant"
            assert "food_delivery" in body["scene_ids"]

            agent_id = body["agent"]["agent_id"]
            creds = body["credentials"]
            assert creds["key_custody"] == "server_side_revocable"
            assert creds["api_key"], "bootstrap key must be returned once"
            assert validate_api_key_for_agent(agent_id, creds["api_key"])
            assert has_minted_api_key(agent_id)

            # Karma custody-holds a per-agent key that is NOT the platform key.
            assert has_agent_key(agent_id)
            signer = load_agent_signer(agent_id)
            assert signer is not None
            assert signer.public_key_b64 == body["agent"]["public_key"]

            # The prod gates we care about actually closed.
            assert body["p1_ready"] is True, body.get("p1_status")
            gaps = (body.get("p1_status") or {}).get("gaps") or []
            assert gaps == [], gaps

            st = await client.get(f"/v1/agents/{agent_id}/p1-status")
            assert st.status_code == 200

            mine = await client.get("/v1/agents/mine", headers={"X-Karma-Identity-Id": OWNER})
            assert mine.status_code == 200, mine.text
            listed = mine.json()["agents"]
            row = next(a for a in listed if a["agent_id"] == agent_id)
            assert row["owner_identity_id"] == OWNER
            assert row["identity_class"] == "merchant"
            assert row["p1_ready"] is True

            other = await client.get("/v1/agents/mine", headers={"X-Karma-Identity-Id": OTHER})
            assert other.status_code == 200
            assert other.json()["agents"] == []

            rev = await client.post(
                "/v1/agents/owner-revoke",
                json={"agent_id": agent_id},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert rev.status_code == 200, rev.text
            assert rev.json()["agent_key_revoked"] is True
            assert has_agent_key(agent_id) is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_owner_connect_rejects_placeholder_service_specs(db_session, monkeypatch):
    """Prod must refuse an owner connect that ships no real hard metrics."""
    monkeypatch.setattr("api.routes.agents.is_prod_like_env", lambda: True)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/v1/agents/owner-connect",
                json=_payload(answers={"industry_ids": ["food_delivery"]}),
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert r.status_code == 400, r.text
            assert "service_specs" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()
