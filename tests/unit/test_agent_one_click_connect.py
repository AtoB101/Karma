"""One-click vertical agent connect."""
from __future__ import annotations

import pytest
import pytest_asyncio
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app import app
from api.middleware.auth import validate_api_key_for_agent
from db.models.orm import Base
from db.session import get_db
from services.agent_bootstrap_credentials import reset_bootstrap_keys
from services.agent_one_click import resolve_one_click
from services.agent_onboarding_template import OnboardingError, load_onboarding_catalog
from services.onboarding_authorization import (
    current_prompt,
    reset_onboarding_flows,
    respond_onboarding,
    start_onboarding,
)

_KEY = "0x" + "11" * 32
_ACCOUNT = Account.from_key(_KEY)


def _sign(message: str) -> str:
    return "0x" + _ACCOUNT.sign_message(encode_defunct(text=message)).signature.hex()


def _complete_onboarding(identity_id: str) -> str:
    """Drive the seven-step consent flow to completion; returns flow_id."""
    r = start_onboarding(identity_id=identity_id, profile_id="merchant", started_by="agent-test")
    flow_id = r["flow"]["flow_id"]
    for _ in range(7):
        p = current_prompt(flow_id)["prompt"]
        if p is None:
            break
        if p["prompt_type"] == "wallet_sign":
            sig = _sign(p["payload"]["sign_message"])
            r = respond_onboarding(flow_id=flow_id, action="sign", value={"address": _ACCOUNT.address, "signature": sig})
        elif p["prompt_type"] == "matching_code":
            r = respond_onboarding(flow_id=flow_id, action="confirm", value={"code": p["payload"]["match_code"]})
        elif p["prompt_type"] in ("yes_no", "ack"):
            r = respond_onboarding(flow_id=flow_id, action="confirm", value={"profile_id": "merchant"})
        else:
            r = respond_onboarding(flow_id=flow_id, action="continue")
    assert r["status"] == "complete"
    return flow_id


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
    reset_onboarding_flows()
    load_onboarding_catalog.cache_clear()
    yield
    reset_bootstrap_keys()
    reset_onboarding_flows()
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
async def test_one_click_without_onboarding_mints_restricted_key(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/agents/one-click-connect",
                json={"side": "seller", "vertical": "food", "display_name": "Test Food Agent"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["schema_version"] == "karma-agent-one-click-v1"
            assert "food_delivery" in body["scene_ids"]
            creds = body["credentials"]
            assert creds["api_key"]
            # No completed consent flow => the minted key is permission-scoped, not full.
            assert creds["onboarding_required"] is True
            assert creds["key_scope"] == ["grant:apply"]
            agent_id = body["agent"]["agent_id"]
            assert validate_api_key_for_agent(agent_id, creds["api_key"])
            st = await client.get(f"/v1/agents/{agent_id}/p1-status")
            assert st.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_one_click_with_completed_onboarding_mints_full_key(db_session):
    async def override_get_db():
        yield db_session

    flow_id = _complete_onboarding("owner-123")

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/agents/one-click-connect",
                json={
                    "side": "seller",
                    "vertical": "food",
                    "display_name": "Authorized Food Agent",
                    "onboarding_flow_id": flow_id,
                },
            )
            assert r.status_code == 200, r.text
            creds = r.json()["credentials"]
            assert creds["api_key"]
            assert creds.get("key_scope") == ["*"]
            assert creds.get("onboarding_required") is not True
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
