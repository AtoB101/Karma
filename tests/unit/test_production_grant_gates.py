"""Production-mode tightening for the spending-grant / P1 boundary.

Item 5: in a production APP_ENV the dev relaxations must be off — template
example specs and auto-acknowledged responsibility cannot silently pass, and
p1_ready / the spending grant gate must not be able to fall back to dev mode.
These pin the *behaviour* (not just the settings validator) so the relaxations
cannot regress behind a flag flip.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app import app
from config.settings import settings
from db.models.orm import Base
from db.session import get_db
from services.agent_onboarding_template import load_onboarding_catalog
from services.human_confirmation_policy import allow_demo_confirmation_bypass


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/prod_grant.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _clean_catalog():
    load_onboarding_catalog.cache_clear()
    yield
    load_onboarding_catalog.cache_clear()


@pytest.fixture
def production_env(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    return settings


def test_demo_bypass_is_off_in_production(production_env):
    assert allow_demo_confirmation_bypass() is False


@pytest.mark.asyncio
async def test_connect_template_rejects_example_specs_in_production(db_session, production_env):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/agents/connect-from-template",
                json={
                    "profile_id": "merchant",
                    "answers": {},
                    "allow_example_specs": True,
                    "owner_identity_id": "owner-prod-merchant",
                },
            )
            assert r.status_code == 400, r.text
            assert "service_specs" in r.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_connect_template_requires_responsibility_ack_in_production(db_session, production_env):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/agents/connect-from-template",
                json={
                    "profile_id": "user",
                    "answers": {},
                    "owner_identity_id": "owner-prod-user",
                },
            )
            assert r.status_code == 400, r.text
            assert "responsibility_ack" in r.text
    finally:
        app.dependency_overrides.clear()
