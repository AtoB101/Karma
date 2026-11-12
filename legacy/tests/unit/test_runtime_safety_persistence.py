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

from datetime import datetime, timedelta

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


async def test_manual_override_timestamp_survives_restart(safety_factory):
    """人工放闸的时刻要落库：重启之后自动刹车仍然不许拿旧证据复燃。

    这一列是「迟滞」的凭据（见 api/routes/security.py 的 ``manual_override_at``
    判断）。只活在内存里的话，一次 recreate 就能让那条规则凭空消失。
    """
    # 先把人工放闸时刻推到一个明确的「过去」：断言不靠时钟精度（Windows 上两次
    # utcnow() 可能落在同一个 tick 里）。
    past = datetime.utcnow() - timedelta(hours=1)
    runtime_safety._STATE = runtime_safety.get_runtime_safety_mode_state().model_copy(
        update={"manual_override_at": past}
    )

    await runtime_safety.set_runtime_safety_mode_persisted(
        enabled=True, reason="auto brake: denied rate", actor_id="security-ops"
    )
    # 自动刹车不许改动这一列。
    assert runtime_safety.get_runtime_safety_mode_state().manual_override_at == past

    await runtime_safety.set_runtime_safety_mode_persisted(
        enabled=False, reason="reviewed", actor_id="ops-admin"
    )
    stamped = runtime_safety.get_runtime_safety_mode_state().manual_override_at
    assert stamped is not None
    assert stamped > past

    _restart_process()
    await runtime_safety.hydrate_runtime_safety_mode()
    restored = runtime_safety.get_runtime_safety_mode_state().manual_override_at
    assert restored is not None
    assert abs((restored - stamped).total_seconds()) < 1

    # 之后再自动刹车（enabled=True）不许把这一列抹掉 —— 否则闸一落下，迟滞就没了。
    await runtime_safety.set_runtime_safety_mode_persisted(
        enabled=True, reason="auto brake: denied rate again", actor_id="security-ops"
    )
    assert runtime_safety.get_runtime_safety_mode_state().manual_override_at == restored


async def test_operational_pause_clear_stamps_the_manual_override(safety_factory):
    """运维走的是 /v1/admin/controls/pauses —— 全线放闸同样要盖时间戳。"""
    past = datetime.utcnow() - timedelta(hours=1)
    runtime_safety._STATE = runtime_safety.get_runtime_safety_mode_state().model_copy(
        update={"manual_override_at": past}
    )

    await runtime_safety.set_runtime_operational_pauses_persisted(
        pause_new_lock=True,
        pause_new_authorization=True,
        pause_new_task=True,
        pause_new_settlement=True,
        reason="auto brake", actor_id="security-ops",
    )
    # 拉闸不动人工放闸时刻。
    assert runtime_safety.get_runtime_safety_mode_state().manual_override_at == past

    await runtime_safety.set_runtime_operational_pauses_persisted(
        pause_new_lock=False,
        pause_new_authorization=False,
        pause_new_task=False,
        pause_new_settlement=False,
        reason="cleared by operator", actor_id="ops-admin",
    )
    cleared = runtime_safety.get_runtime_safety_mode_state().manual_override_at
    assert cleared is not None
    assert cleared > past


def test_migration_columns_match_the_model():
    """建表（0060）与后续加列（0065）合起来必须和 ORM 模型一一对应。

    这条不是形式主义：0060 第一次上线时正是栽在「应用先 create_all、迁移后到」上 ——
    CI 报了 ``DuplicateTableError: relation "runtime_safety_mode" already exists``
    （见该迁移的说明）。两边列名再对不上，就等于在库里留一颗「模型和 schema
    不一致」的定时炸弹，而这张表是刹车开关。
    """
    import re
    from pathlib import Path

    from db.models.orm import RuntimeSafetyModeModel

    root = Path(__file__).resolve().parents[2]
    versions = root / "db" / "migrations" / "versions"
    src = (versions / "0060_runtime_safety_mode.py").read_text(encoding="utf-8")
    # 到 PRIMARY KEY 为止；不能用 ")" 切 —— 列定义里有 VARCHAR(512)。
    body = src.split("CREATE TABLE IF NOT EXISTS runtime_safety_mode (", 1)[1].split(
        "PRIMARY KEY", 1
    )[0]
    in_migration = set(re.findall(r"^\s+([a-z_]+)\s+[A-Z]", body, re.M))

    # 0065 起这张表靠 ALTER 加列 —— 只认挂在 runtime_safety_mode 上的 ADD COLUMN。
    for extra in sorted(versions.glob("*.py")):
        for _, column in re.findall(
            r"ALTER TABLE runtime_safety_mode(.+?)ADD COLUMN IF NOT EXISTS ([a-z_]+)",
            extra.read_text(encoding="utf-8"),
            re.S,
        ):
            in_migration.add(column)

    in_model = {column.name for column in RuntimeSafetyModeModel.__table__.columns}
    assert in_migration == in_model, (sorted(in_migration), sorted(in_model))
