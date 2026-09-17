"""P0-4 回归：资金台账在并发下必须「恰好一次」。

历史缺陷（2026-09-17 实测，修复前）：
    15 个并发 ``POST /v1/capacity/{id}/lock`` 全部返回 200，账上只 +1 笔；
    12 个并发 ``/release`` 同样只 -1 笔（另有并发超额释放）。
根因是「读 -> 改 -> 写」整行覆盖：多个请求各自读到同一份旧快照，后写覆盖先写。

修法见 ``services/atomic_ledger.py``：把「校验 + 变更」压成一条带 WHERE 守卫的
``UPDATE ... SET col = col + delta``，由数据库保证串行化。

本文件是守门用例：并发 15 路，断言每一笔成功都真的落账（不多不少），
并且余额不足时由数据库原子拒绝、绝不允许超额释放。
"""
from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.app import app
from db.models.orm import Base, CapacityModel
from db.session import get_db
from services import atomic_ledger

HEADERS = {"X-Karma-Identity-Id": "kid_atomic_probe"}
PARALLEL = 15


# 测试用的 SQLite 文件必须落在仓库内：Windows 上系统 Temp 目录
# （pytest 的 tmp_path 默认位置）在受控环境下不可写。
_TMP_ROOT = Path(__file__).resolve().parents[2] / ".atomic-ledger-tmp"


@pytest_asyncio.fixture
async def concurrent_client():
    """每个请求独占一个 session 的客户端 —— 只有这样才能真正并发。

    常规的 ``client`` fixture 让所有请求共享同一个 AsyncSession，
    并发下 SQLAlchemy 会串行甚至报错，测不出丢更新。
    """
    workdir = _TMP_ROOT / uuid.uuid4().hex
    workdir.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(
        "sqlite+aiosqlite:///" + (workdir / "atomic_ledger.db").as_posix(),
        connect_args={"timeout": 30},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, factory
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
        shutil.rmtree(workdir, ignore_errors=True)


@pytest.fixture
def widen_race(monkeypatch):
    """把并发窗口撑开，让 N 路请求真的同时进入台账写入。

    默认情况下 ASGI + SQLite 会把并发请求排成近乎串行（限流器连 Redis 的 1 秒
    连接超时还顺带把它们错开了），而串行是测不出丢更新的。这里在写账前插入一次
    短 sleep：它不改变被测代码的语义，只是让「并发」名副其实 —— 修复后的实现是
    单条原子 UPDATE，窗口再大也不会丢；旧的「读-改-写」在这个窗口里必然丢。
    """
    real = atomic_ledger.apply_delta

    async def widened(*args, **kwargs):
        await asyncio.sleep(0.05)
        return await real(*args, **kwargs)

    monkeypatch.setattr(atomic_ledger, "apply_delta", widened)
    return widened


async def _fire(client, method, url, *, n, json=None):
    calls = [client.request(method, url, json=json, headers=HEADERS) for _ in range(n)]
    return await asyncio.gather(*calls, return_exceptions=True)


def _codes(responses):
    return [getattr(r, "status_code", "ERR") for r in responses]


async def _capacity(client, identity_id="kid_atomic_probe"):
    resp = await client.get("/v1/capacity/" + identity_id, headers=HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 1) 并发锁仓：成功的每一笔都必须落账
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_locks_credit_every_success(concurrent_client, widen_race):
    client, _ = concurrent_client
    responses = await _fire(client, "POST", "/v1/capacity/kid_atomic_probe/lock", n=PARALLEL, json={"amount": 1.0})
    codes = _codes(responses)
    rejections = [c for c in codes if c not in (200, 429, 503)]
    assert not rejections, "并发锁仓出现非预期错误: %s" % rejections
    ok = codes.count(200)
    # 修复前这里恒为 1；修复后应当每一路都成功。
    assert ok >= 10, "并发锁仓成功率过低（丢更新的典型症状）: %s" % codes

    state = await _capacity(client)
    assert state["total_locked_usdc"] == pytest.approx(ok * 1.0)
    assert state["total_bill_credits"] == pytest.approx(ok * 1.0)
    assert state["available_credits"] == pytest.approx(ok * 1.0)


# ---------------------------------------------------------------------------
# 2) 并发减仓：恰好放掉「余额允许的那几笔」，绝不为负
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_releases_are_exact_and_never_negative(concurrent_client, widen_race):
    client, _ = concurrent_client
    lock = await client.post("/v1/capacity/kid_atomic_probe/lock", json={"amount": 100.0}, headers=HEADERS)
    assert lock.status_code == 200, lock.text

    responses = await _fire(client, "POST", "/v1/capacity/kid_atomic_probe/release", n=PARALLEL, json={"amount": 10.0})
    codes = _codes(responses)
    ok = codes.count(200)
    # 100 USDC 只够放 10 笔 × 10；修复前 15 笔全会 "成功" 并把账减穿。
    assert ok == 10, "并发减仓没有恰好执行 10 笔: %s" % codes
    assert codes.count(409) == PARALLEL - 10, "余额不足的减仓必须被 409 原子拒绝: %s" % codes

    state = await _capacity(client)
    assert state["available_credits"] == pytest.approx(0.0)
    assert state["total_locked_usdc"] == pytest.approx(0.0)
    assert state["total_bill_credits"] == pytest.approx(0.0)
    assert state["released_credits"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 3) 台账层：跨 session 的并发增量不能丢
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parallel_deltas_on_one_row_are_additive(concurrent_client):
    _, factory = concurrent_client
    identity = "kid_atomic_layer"
    async with factory() as session:
        await atomic_ledger.ensure_row(
            session, CapacityModel, "identity_id", identity,
            defaults={"total_locked_usdc": 0.0, "available_credits": 0.0},
        )
        await session.commit()

    async def bump():
        async with factory() as session:
            rows = await atomic_ledger.apply_delta(
                session, CapacityModel, "identity_id", identity, {"available_credits": 1.0}
            )
            await session.commit()
            return rows

    rows = await asyncio.gather(*[bump() for _ in range(24)])
    assert all(r == 1 for r in rows), "原子增量没有命中目标行: %s" % rows

    async with factory() as session:
        row = await atomic_ledger.reload(session, CapacityModel, identity)
    assert row.available_credits == pytest.approx(24.0)


# ---------------------------------------------------------------------------
# 4) 守卫语义：读到的责任额度被并发改动后，写入必须落空
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guard_voids_write_when_responsibility_changed_mid_flight(concurrent_client):
    _, factory = concurrent_client
    identity = "kid_atomic_guard"
    async with factory() as session:
        await atomic_ledger.ensure_row(
            session, CapacityModel, "identity_id", identity,
            defaults={"total_locked_usdc": 50.0, "total_bill_credits": 50.0, "available_credits": 50.0},
        )
        await session.commit()

    async with factory() as session:
        snapshot = await atomic_ledger.reload(session, CapacityModel, identity)
        guards = atomic_ledger.responsibility_snapshot_guards(snapshot)

    # 另一路先把责任额度改了（模拟并发接单占额）。
    async with factory() as session:
        await atomic_ledger.apply_delta_or_raise(
            session, CapacityModel, "identity_id", identity,
            {"reserved_credits": 10.0, "available_credits": -10.0},
        )
        await session.commit()

    async with factory() as session:
        with pytest.raises(atomic_ledger.LedgerConflict):
            await atomic_ledger.apply_delta_or_raise(
                session, CapacityModel, "identity_id", identity,
                {"available_credits": -20.0, "released_credits": 20.0},
                guards=guards,
                message="责任额度已被并发改动",
            )
        await session.rollback()

    async with factory() as session:
        row = await atomic_ledger.reload(session, CapacityModel, identity)
    assert row.available_credits == pytest.approx(40.0)
    assert row.released_credits == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 5) 守卫语义：余额不足必须原子拒绝（不写一半）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insufficient_balance_is_rejected_atomically(concurrent_client):
    _, factory = concurrent_client
    identity = "kid_atomic_insufficient"
    async with factory() as session:
        await atomic_ledger.ensure_row(
            session, CapacityModel, "identity_id", identity,
            defaults={"total_locked_usdc": 5.0, "total_bill_credits": 5.0, "available_credits": 5.0},
        )
        await session.commit()

    async with factory() as session:
        with pytest.raises(atomic_ledger.LedgerConflict):
            await atomic_ledger.apply_delta_or_raise(
                session, CapacityModel, "identity_id", identity,
                {"available_credits": -10.0, "released_credits": 10.0},
                guards=[lambda C: C.available_credits >= 10.0],
            )
        await session.rollback()

    async with factory() as session:
        row = await atomic_ledger.reload(session, CapacityModel, identity)
    assert row.available_credits == pytest.approx(5.0)
    assert row.released_credits == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 6) 并发建行：并发 ensure_row 只能落一行
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_ensure_row_creates_exactly_one_row(concurrent_client):
    _, factory = concurrent_client
    identity = "kid_atomic_ensure"

    async def ensure():
        async with factory() as session:
            await atomic_ledger.ensure_row(
                session, CapacityModel, "identity_id", identity,
                defaults={"total_locked_usdc": 0.0, "available_credits": 0.0},
            )
            await session.commit()

    await asyncio.gather(*[ensure() for _ in range(12)])
    async with factory() as session:
        rows = list((await session.execute(
            __import__("sqlalchemy").select(CapacityModel).where(CapacityModel.identity_id == identity)
        )).scalars())
    assert len(rows) == 1
