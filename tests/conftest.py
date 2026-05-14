"""
Karma — Test Configuration & Shared Fixtures
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import settings
from db.models.orm import Base
from db.session import get_db
from api.app import app
from core.schemas import (
    AgentRole, TaskContract, ExecutionReceipt, ToolStatus,
)
from core.hooks.hook_layer import InMemoryReceiptStore

# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Test database (SQLite in-memory)
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def client_sec(db_session, monkeypatch):
    """HTTP client with API key for routes that always require credentials (e.g. /v1/security)."""
    monkeypatch.setattr(
        settings,
        "auth_api_keys",
        "sec-route-default:sec-route-default-secret-abcdef12",
    )

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    headers = {"X-Karma-Api-Key": "karma_sec-route-default_sec-route-default-secret-abcdef12"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Domain fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def receipt_store():
    return InMemoryReceiptStore()


@pytest.fixture
def sample_contract() -> TaskContract:
    return TaskContract(
        client_agent_id="client-test-001",
        worker_agent_id="worker-test-001",
        title="Test Captioning Task",
        description="Caption 5 images for testing",
        expected_output_schema={"type": "object"},
        expected_step_count=5,
        escrow_amount=25.0,
        currency="USD",
        deadline_at=datetime.utcnow() + timedelta(hours=2),
    )


@pytest.fixture
def make_receipt():
    def _make(
        task_id: str,
        step: int,
        status: ToolStatus = ToolStatus.SUCCESS,
        duration_ms: int = 150,
        tool_name: str | None = None,
    ) -> ExecutionReceipt:
        base = datetime.now(timezone.utc) + timedelta(seconds=step * 3)
        return ExecutionReceipt(
            task_id=task_id,
            agent_id="worker-test-001",
            step_index=step,
            tool_name=tool_name or f"tool.step{step}",
            input_hash="a" * 64,
            output_hash=("b" * 62) + f"{step:02d}",
            started_at=base,
            ended_at=base + timedelta(milliseconds=duration_ms),
            duration_ms=duration_ms,
            status=status,
        )
    return _make
