"""
Conftest for verifier-network tests.
Uses in-memory SQLite to avoid full dependency chain.
"""
from __future__ import annotations

from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.orm import Base

# Ensure verifier network models are registered on Base.metadata
import decentralized_verifier.models  # noqa: F401

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client with overridden DB dependency."""
    from api.app import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides = {}

    from db.session import get_db
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client_sec(db_session: AsyncSession, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    """带运维 key 的客户端：裁决挑战现在是仲裁员 / 管理员白名单动作。

    与根 conftest 的 ``client_sec`` 同一套路 —— 把 ``sec-route-default`` 同时写进
    管理员与仲裁员白名单，否则收紧后的 ``/resolve`` 会按设计 403（那是产品行为，
    不是测试环境该有的样子）。
    """
    from api.app import app
    from config.settings import settings
    from db.session import get_db

    monkeypatch.setattr(
        settings, "auth_api_keys", "sec-route-default:sec-route-default-secret-abcdef12"
    )
    monkeypatch.setattr(settings, "admin_actor_ids", "sec-route-default")
    monkeypatch.setattr(settings, "arbitrator_actor_ids", "sec-route-default")

    async def override_get_db():
        yield db_session

    app.dependency_overrides = {}
    app.dependency_overrides[get_db] = override_get_db

    headers = {"X-Karma-Api-Key": "karma_sec-route-default_sec-route-default-secret-abcdef12"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        yield ac

    app.dependency_overrides.clear()
