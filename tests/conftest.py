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
# Rate limit isolation (prevent cross-test memory pollution)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_rate_limits():
    """Clear in-memory rate limit windows before each test."""
    from api.middleware.rate_limit import clear_memory_rate_limits
    clear_memory_rate_limits()


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _legacy_bearer_keys_allowed_in_tests(monkeypatch) -> None:
    """Runtime Key「必须指名 agent」这条闸门，在测试里默认放开。

    生产默认是**开**的（``RUNTIME_REQUIRE_AGENT_BINDING=true``）：不指名 agent 就铸不出
    钥匙，「服务端托管」的不记名钥匙一律拒 —— 光捡到 ``KRM_RT_…`` 什么都做不了。

    但仓库里大量用例考的是网关机制本身（限额 / 结算 / 验签 / 派发），
    它们用 ``create_runtime_key_record(agent_binding=None)`` 造一把省事的钥匙就够了。
    这里把闸门放开，让那些用例继续考它本来要考的东西；
    「闸门真的拦得住」由 ``tests/integration/test_console_key_to_agent_e2e.py``
    与 ``tests/unit/test_runtime_agent_binding_gate.py`` 专门考。
    """
    monkeypatch.setattr(settings, "runtime_require_agent_binding", False)


@pytest.fixture(autouse=True)
def reset_runtime_safety_mode_between_tests() -> None:
    """Global runtime safety mode is in-process; clear it so integration tests do not leak pauses."""
    from services.runtime_safety import set_runtime_safety_mode

    set_runtime_safety_mode(enabled=False, reason="pytest autouse reset", actor_id="pytest")
    yield
    set_runtime_safety_mode(enabled=False, reason="pytest autouse reset", actor_id="pytest")


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
def activate_identity(db_session):
    """把一个主身份直接标成「已激活」（= 本人实名认证通过）。

    生产里只有 verifier 走 ``/v1/identity/{id}/verification/verify`` 才能置位，而且
    不允许自己批自己；测试里直接写 ``identity_verifications`` 一行，免得每个用例都要
    先造一个复核岗身份。
    """
    from db.models.orm import IdentityVerificationModel

    async def _activate(*identity_ids: str) -> None:
        for identity_id in identity_ids:
            # 幂等：同一用例里两次接单都调它，不能第二次直接撞主键。
            if await db_session.get(IdentityVerificationModel, identity_id) is None:
                db_session.add(
                    IdentityVerificationModel(
                        identity_id=identity_id, status="verified", level="basic"
                    )
                )
        await db_session.commit()

    return _activate


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
    """HTTP client with API key for routes that always require credentials (e.g. /v1/security).

    这个 key 代表**平台运维**那把钥匙，所以同时把它写进三张白名单
    （管理员 / 仲裁员 / 治理身份发放方）。否则收紧后的
    ``/v1/security`` 与 ``/v1/admin`` 会按设计返回 403 —— 那是产品行为，
    不是测试环境该有的样子。
    """
    monkeypatch.setattr(
        settings,
        "auth_api_keys",
        "sec-route-default:sec-route-default-secret-abcdef12",
    )
    monkeypatch.setattr(settings, "admin_actor_ids", "sec-route-default")
    monkeypatch.setattr(settings, "arbitrator_actor_ids", "sec-route-default")
    monkeypatch.setattr(settings, "governance_verifier_ids", "sec-route-default")

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
