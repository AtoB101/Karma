"""One-click vertical agent connect."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app import app
from api.middleware.auth import validate_api_key_for_agent
from db.models.orm import Base
from db.session import get_db
from services.agent_bootstrap_credentials import reset_bootstrap_keys
from services.agent_one_click import resolve_one_click
from services.agent_onboarding_template import OnboardingError, load_onboarding_catalog


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
def _clean_keys_and_catalog():
    reset_bootstrap_keys()
    load_onboarding_catalog.cache_clear()
    yield
    reset_bootstrap_keys()
    load_onboarding_catalog.cache_clear()


def test_resolve_vertical_aliases():
    food = resolve_one_click(side="seller", vertical="food", display_name="Bowl")
    assert food["profile_id"] == "merchant"
    assert food["industry_id"] == "food_delivery"
    hotel = resolve_one_click(side="seller", vertical="hotel")
    assert hotel["industry_id"] == "hotel_booking"
    buyer = resolve_one_click(side="buyer", vertical="user")
    assert buyer["profile_id"] == "user"
    ent = resolve_one_click(side="seller", vertical="enterprise")
    assert ent["profile_id"] == "enterprise"
    cs = resolve_one_click(side="seller", vertical="customer_service")
    assert cs["industry_id"] == "api_tool_call"
    with pytest.raises(OnboardingError):
        resolve_one_click(side="seller", vertical="not-a-real-vertical-xyz")


@pytest.mark.asyncio
async def test_one_click_seller_food_mints_usable_key(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/agents/one-click-connect",
                json={
                    "side": "seller",
                    "vertical": "food",
                    "display_name": "Test Food Agent",
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["schema_version"] == "karma-agent-one-click-v1"
            assert body["side"] == "seller"
            assert "food_delivery" in body["scene_ids"]
            assert body["credentials"]["api_key"]
            agent_id = body["agent"]["agent_id"]
            api_key = body["credentials"]["api_key"]
            assert validate_api_key_for_agent(agent_id, api_key)
            # p1 status reachable
            st = await client.get(f"/v1/agents/{agent_id}/p1-status")
            assert st.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_one_click_buyer_and_verticals_list(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            verts = await client.get("/v1/agents/one-click-verticals")
            assert verts.status_code == 200
            assert any(v["vertical"] == "hotel" for v in verts.json()["verticals"])

            r = await client.post(
                "/v1/agents/one-click-connect",
                json={"side": "buyer", "display_name": "Buyer One"},
            )
            assert r.status_code == 200, r.text
            assert r.json()["profile_id"] == "user"
            assert r.json()["next_steps"]
    finally:
        app.dependency_overrides.clear()
