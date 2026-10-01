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
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import settings
from db.models.orm import Base, RuntimeNonceLogModel
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
def _no_chain_event_lookups_in_unit_tests(monkeypatch) -> None:
    """单元测试永远不碰链。

    回查终局交易（`allowance_escrow.find_binding_event_tx`，见
    `escrow_settlement.recover_money_tx_hash`）是给「链上已落定、台账没记下那笔」
    用的兜底。用例里没有 RPC，默认让它返回「找不到」；要考这条回查的用例自己
    覆盖这个替身（`tests/unit/test_escrow_settlement.py`）。
    """
    from services.chain import allowance_escrow as _escrow
    from services.chain import escrow_settlement as _bridge

    monkeypatch.setattr(_escrow, "find_binding_event_tx", lambda **_kw: None)
    # 回查失败后的冷却表是进程内的：用例之间必须清掉，否则前一个用例的「查不到」
    # 会让后一个用例连查都不查（考这条回查的用例会间歇性红）。
    _bridge._recover_failed_at.clear()


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
        # nonce 台账是**当场提交**的（跨进程防重放的要求，见 services/runtime_nonce_log.py），
        # 所以它不跟着上面那句 rollback 消失。不清掉的话，下一个用例拿着同样的 nonce
        # 会直接拿到上一个用例的「原结果」—— 那是测试互相污染，不是产品行为。
        try:
            await session.execute(delete(RuntimeNonceLogModel))
            await session.commit()
        except Exception:  # noqa: BLE001 - 清理失败不该让用例失败
            await session.rollback()


# ---------------------------------------------------------------------------
# Cross-test DB isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _purge_shared_test_db(test_engine):
    """会话级共享内存库：每个用例收尾时把自己的行清干净。

    ``test_engine`` 是 session 级的 ``sqlite+aiosqlite:///:memory:``，整个进程共用
    一张库。用例里 ``commit`` 出来的行不随 ``db_session`` 的 rollback 消失，会以
    「谁先跑」的形式污染后面的用例 —— 本仓库真有三条用例是这样被顶红的。

    这里在每个用例结束后清空 ``Base.metadata`` 下的所有表，让每个用例都从空库开始：
    不再依赖用例之间的先后顺序，也不要求每个用例自己记得清理。

    顺序：本 fixture 是 autouse，同一 scope 下先于 ``db_session`` 建立、后于它拆除，
    清理时不会和 ``db_session`` 抢同一个连接。
    ``tests/test_verifier_network/conftest.py`` 自带 function 级 engine，天然隔离；
    这里解析到的是它自己的 ``test_engine``，清完随即 dispose。

    外键：仓库里没有任何地方打开过 ``PRAGMA foreign_keys``（SQLite 默认关闭），
    所以按 ``sorted_tables`` 逆序删（先子表后父表）就够，不必先关外键。
    """
    yield
    factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with factory() as session:
        try:
            existing = set(
                (
                    await session.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table'")
                    )
                ).scalars().all()
            )
            for table in reversed(Base.metadata.sorted_tables):
                if table.name in existing:
                    await session.execute(delete(table))
            await session.commit()
        except Exception:  # noqa: BLE001 - 清理失败不该让用例失败
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
