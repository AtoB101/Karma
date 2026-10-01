"""刹车必须活过重启 —— 它不能只活在进程内存里。

背景（2026-10-01 安全审计）
---------------------------
``services/runtime_safety.py`` 的 ``_STATE`` 原本是进程内变量，两个后果都在钱路上：

* ``docker compose up -d --force-recreate app``（或容器 OOM 重启）之后，之前手动或
  自动拉下的刹车自动弹回「关」—— 正好在最需要它的时刻失效；
* ``deploy/Dockerfile.api`` 写的是 ``--workers 4``，一个 worker 拉下的刹车，
  另一个 worker 照常住放行。

修法是把开关落进单行表 ``runtime_safety_mode``（migration 0060），本文件考的就是
「重启之后还在」。用例用 ``set_session_factory_for_tests`` 把落库会话指到测试引擎，
走的仍然是生产那一条 ``persist_runtime_safety_mode`` 代码路径。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.schemas import RuntimeSafetyModeState
from db.models.orm import RuntimeSafetyModeModel
from services import runtime_safety


@pytest.fixture
def safety_factory(test_engine):
    """落库会话指向测试引擎；用完恢复成生产默认（AsyncSessionLocal）。"""
    factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    runtime_safety.set_session_factory_for_tests(factory)
    yield factory
    runtime_safety.set_session_factory_for_tests(None)
    runtime_safety._STATE = RuntimeSafetyModeState()


def _restart_process() -> None:
    """模拟一次「进程重启」：内存缓存清零，只剩库里的那一行。"""
    runtime_safety._STATE = RuntimeSafetyModeState()


async def _rows(factory) -> list[RuntimeSafetyModeModel]:
    async with factory() as session:
        res = await session.execute(select(RuntimeSafetyModeModel))
        return list(res.scalars().all())


async def test_brake_survives_restart(safety_factory):
    await runtime_safety.set_runtime_safety_mode_persisted(
        enabled=True, reason="anchor breach", actor_id="ops-admin"
    )

    _restart_process()
    assert runtime_safety.get_runtime_safety_mode_state().enabled is False  # 缓存确实空了

    await runtime_safety.hydrate_runtime_safety_mode()

    state = runtime_safety.get_runtime_safety_mode_state()
    assert state.enabled is True
    assert state.reason == "anchor breach"
    assert state.triggered_by == "ops-admin"
    # 灌回来之后闸门真的拦得住 —— 这不是只改了一个展示字段。
    with pytest.raises(HTTPException) as ei:
        runtime_safety.assert_runtime_operation_allowed("new_settlement")
    assert ei.value.status_code == 503
    assert len(await _rows(safety_factory)) == 1


async def test_turning_the_brake_off_also_survives_restart(safety_factory):
    await runtime_safety.set_runtime_safety_mode_persisted(
        enabled=True, reason="anchor breach", actor_id="ops-admin"
    )
    await runtime_safety.set_runtime_safety_mode_persisted(
        enabled=False, reason="resolved", actor_id="ops-admin"
    )

    _restart_process()
    await runtime_safety.hydrate_runtime_safety_mode()

    state = runtime_safety.get_runtime_safety_mode_state()
    assert state.enabled is False
    assert state.reason == "resolved"
    runtime_safety.assert_runtime_operation_allowed("new_settlement")  # 不抛 = 放行
    # 开关是单行 —— 反复切换不该长出新行。
    assert len(await _rows(safety_factory)) == 1


async def test_operational_pauses_survive_restart(safety_factory):
    await runtime_safety.set_runtime_operational_pauses_persisted(
        pause_new_lock=False,
        pause_new_authorization=False,
        pause_new_task=False,
        pause_new_settlement=True,
        reason="settlement incident",
        actor_id="ops-admin",
    )

    _restart_process()
    await runtime_safety.hydrate_runtime_safety_mode()

    state = runtime_safety.get_runtime_safety_mode_state()
    assert state.pause_new_settlement is True
    assert state.enabled is True
    with pytest.raises(HTTPException) as ei:
        runtime_safety.assert_runtime_operation_allowed("new_settlement")
    assert ei.value.status_code == 503
    # P0-14：暂停必须仍然允许**释放**未用额度（否则钱被永久锁住）。
    runtime_safety.assert_runtime_operation_allowed("release_unused_capacity")


async def test_hydrate_without_a_row_keeps_the_current_state(safety_factory):
    """全新环境（表里没行）= 什么都不做，别把内存里已有的状态抹掉。"""
    runtime_safety.set_runtime_safety_mode(enabled=True, reason="local", actor_id="ops-admin")
    assert await runtime_safety.hydrate_runtime_safety_mode() is None
    assert runtime_safety.get_runtime_safety_mode_state().enabled is True


async def test_hydrate_is_a_noop_when_content_already_matches(safety_factory):
    await runtime_safety.set_runtime_safety_mode_persisted(
        enabled=True, reason="anchor breach", actor_id="ops-admin"
    )
    assert await runtime_safety.hydrate_runtime_safety_mode() is None


async def test_persist_failure_does_not_disable_the_brake(safety_factory):
    """库写不进去时，刹车必须仍然生效（安全的那一侧），只是会喊。"""

    class _BoomSession:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *exc_info):
            return False

    runtime_safety.set_session_factory_for_tests(lambda: _BoomSession())
    try:
        state = await runtime_safety.set_runtime_safety_mode_persisted(
            enabled=True, reason="anchor breach", actor_id="ops-admin"
        )
    finally:
        runtime_safety.set_session_factory_for_tests(safety_factory)

    assert state.enabled is True
    assert runtime_safety.get_runtime_safety_mode_state().enabled is True
    with pytest.raises(HTTPException):
        runtime_safety.assert_runtime_operation_allowed("new_task")


async def test_anchor_breach_trip_is_persisted(safety_factory, db_session):
    """容量锚被击穿时的那一跳，同样必须落库（它常常正赶上要重启服务查故障）。"""
    from db.models.orm import CapacityModel

    db_session.add(
        CapacityModel(
            identity_id="buyer-anchor",
            total_locked_usdc=0.0,
            total_bill_credits=5.0,
        )
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as ei:
        await runtime_safety.audit_capacity_anchor_and_maybe_trip(db_session)
    assert ei.value.status_code == 503

    _restart_process()
    await runtime_safety.hydrate_runtime_safety_mode()
    state = runtime_safety.get_runtime_safety_mode_state()
    assert state.enabled is True
    assert "capacity anchor breach" in (state.reason or "")
    assert len(await _rows(safety_factory)) == 1
