"""Runtime safety-mode guardrails and capacity anchor audits.

刹车（safety mode / 运维暂停）原本只活在**进程内存**里 —— 模块级 ``_STATE``。
两个后果，都在钱路上：

1. **重启即清零**。``docker compose up -d --force-recreate app``、容器 OOM 重启、
   或者一次改配置重建之后，之前手动或自动拉下的刹车会自己弹回「关」。
   它在最需要它的时刻（故障处理中的重启）失效。
2. **多 worker 各记一份**。一个 worker 拉下的刹车，另一个 worker 照常住放行。
   仓库里 ``deploy/Dockerfile.api`` 写的就是 ``--workers 4`` —— 0058 的 nonce
   重放就是栽在同一件事上（见那份迁移的说明）。

现在的口径是「**内存缓存 + 落库为准**」：

* 快路径仍然只读内存 —— ``assert_runtime_operation_allowed()`` 是同步调用，散落在
  所有动钱的路由里（capacity / vouchers / settlement …），不能变成 await；
* 每次**状态变化**写进 ``runtime_safety_mode``（单行表，见 migration 0060）。
  写用的是**独立会话、当场提交**：这些调用点里有的正处在半截业务写入当中
  （例如 ``services/voucher_lifecycle.py`` 在 ``apply_delta_or_raise`` 之后调审计），
  借它们的会话提交会把半截业务一起带上，跟着它们回滚又会把刹车丢掉；
* 进程启动时灌一次缓存 —— 重启不再把刹车弹回「关」；
* 后台每 ``STATE_REFRESH_SECONDS`` 重灌一次 —— 万一将来上了多 worker，刹车
  最多晚几秒全量生效，而不是只拦住 1/N。

写失败**不会**让刹车失效：内存里的刹车照旧生效（这是安全的那一侧），只记
``safety_mode_persist_failed`` 并留一条安全事件 —— 一个「按了没用」的按钮，
比一个「按了只在当前进程有用、但会喊」的按钮危险得多。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Callable

import structlog
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import RuntimeSafetyModeState
from db.models.orm import CapacityModel, RuntimeSafetyModeModel

logger = structlog.get_logger(__name__)

ANCHOR_EPSILON = 1e-9
DEFAULT_ANCHOR_BREACH_REASON = "capacity anchor breach: total bill credits exceed total locked usdc"

#: 单行表的主键。刹车是一个全局开关，不存在第二行。
_ROW_ID = 1

#: 后台多久从库里重灌一次缓存。单 worker 下它不影响正确性（写是当场的），
#: 兜的是「多 worker 时别的进程改了开关」—— 5 秒对刹车来说够快。
STATE_REFRESH_SECONDS = 5.0

#: 落库的字段 = 开关本身。``last_anchor_audit_at`` / ``total_locked_usdc`` /
#: ``total_bill_credits`` 是每次审计都重算的遥测，**不进库** —— 否则每一笔动钱的
#: 请求都会多写一次库。
_SWITCH_FIELDS = (
    "enabled",
    "reason",
    "triggered_by",
    "triggered_at",
    "pause_new_lock",
    "pause_new_authorization",
    "pause_new_task",
    "pause_new_settlement",
)

_STATE = RuntimeSafetyModeState()

#: 测试注入用。生产走 ``db.session.AsyncSessionLocal``。
_SESSION_FACTORY: Callable[[], Any] | None = None


def _session_factory() -> Callable[[], Any]:
    if _SESSION_FACTORY is not None:
        return _SESSION_FACTORY
    from db.session import AsyncSessionLocal

    return AsyncSessionLocal


def _switch_of(state: RuntimeSafetyModeState) -> dict[str, Any]:
    return {name: getattr(state, name) for name in _SWITCH_FIELDS}


def _switch_of_row(row: RuntimeSafetyModeModel) -> dict[str, Any]:
    return {name: getattr(row, name) for name in _SWITCH_FIELDS}


def set_session_factory_for_tests(factory: Callable[[], Any] | None) -> None:
    """把落库用的会话工厂指向测试引擎（生产不要调它）。"""
    global _SESSION_FACTORY
    _SESSION_FACTORY = factory


def get_runtime_safety_mode_state() -> RuntimeSafetyModeState:
    return _STATE.model_copy()


def set_runtime_safety_mode(
    *,
    enabled: bool,
    reason: str | None = None,
    actor_id: str | None = None,
) -> RuntimeSafetyModeState:
    """只改内存缓存（同步）。

    生产路径请用 ``set_runtime_safety_mode_persisted`` —— 这个同步版本留给
    进程内调用与测试（``tests/conftest.py`` 的 autouse 重置），它**不落库**。
    """
    global _STATE
    now = datetime.utcnow()
    if enabled:
        _STATE = _STATE.model_copy(
            update={
                "enabled": True,
                "reason": reason or _STATE.reason or "manual safety mode enabled",
                "triggered_by": actor_id or "system",
                "triggered_at": _STATE.triggered_at or now,
                "pause_new_lock": True,
                "pause_new_authorization": True,
                "pause_new_task": True,
                "pause_new_settlement": True,
            }
        )
    else:
        _STATE = _STATE.model_copy(
            update={
                "enabled": False,
                "reason": reason or "safety mode disabled",
                "triggered_by": actor_id or "system",
                "triggered_at": now,
                "pause_new_lock": False,
                "pause_new_authorization": False,
                "pause_new_task": False,
                "pause_new_settlement": False,
            }
        )
    return _STATE.model_copy()


def set_runtime_operational_pauses(
    *,
    pause_new_lock: bool,
    pause_new_authorization: bool,
    pause_new_task: bool,
    pause_new_settlement: bool,
    reason: str | None = None,
    actor_id: str | None = None,
) -> RuntimeSafetyModeState:
    """只改内存缓存（同步）。生产路径请用 ``set_runtime_operational_pauses_persisted``。"""
    global _STATE
    now = datetime.utcnow()
    enabled = pause_new_lock or pause_new_authorization or pause_new_task or pause_new_settlement
    _STATE = _STATE.model_copy(
        update={
            "enabled": enabled,
            "reason": reason or ("manual operational pause update" if enabled else "operational pauses disabled"),
            "triggered_by": actor_id or "system",
            "triggered_at": now,
            "pause_new_lock": pause_new_lock,
            "pause_new_authorization": pause_new_authorization,
            "pause_new_task": pause_new_task,
            "pause_new_settlement": pause_new_settlement,
        }
    )
    return _STATE.model_copy()


def assert_runtime_operation_allowed(operation: str) -> None:
    op = (operation or "").strip().lower()
    blocked = False
    if op == "new_lock":
        blocked = _STATE.pause_new_lock
    elif op == "new_authorization":
        blocked = _STATE.pause_new_authorization
    elif op == "new_task":
        blocked = _STATE.pause_new_task
    elif op == "new_settlement":
        blocked = _STATE.pause_new_settlement
    elif op == "release_unused_capacity":
        # P0-14: operational / safety pauses must still allow releasing *available* bill credits
        # (USDC-side unlock is modeled as reducing total_locked for unused available only).
        blocked = False
    else:
        blocked = _STATE.enabled
    if not blocked:
        return
    raise HTTPException(status_code=503, detail=f"safety mode active: blocked operation '{operation}'")


# ---------------------------------------------------------------------------
# 落库 / 灌缓存
# ---------------------------------------------------------------------------


async def persist_runtime_safety_mode() -> bool:
    """把当前内存里的开关写进单行表（独立会话、当场提交）。

    返回 ``True`` = 已落库。``False`` = 写失败（已记错误日志 + 安全事件）：
    内存里的刹车仍然生效，这是刻意选的失败方向。
    """
    values = _switch_of(_STATE)
    values["updated_at"] = datetime.utcnow()
    try:
        factory = _session_factory()
        async with factory() as session:
            row = await session.get(RuntimeSafetyModeModel, _ROW_ID)
            if row is None:
                session.add(RuntimeSafetyModeModel(id=_ROW_ID, **values))
            else:
                for name, value in values.items():
                    setattr(row, name, value)
            await session.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - 落库失败不能让刹车本身失效
        _record_persist_failure(exc)
        return False


def _record_persist_failure(exc: BaseException) -> None:
    """写失败要留痕：这是「刹车没落到库」级别的事，不能只进 stdout。"""
    logger.error("safety_mode_persist_failed", error=str(exc))
    try:
        from services.security_monitoring import (
            SecurityMonitoringEventType,
            record_security_event,
        )

        record_security_event(
            SecurityMonitoringEventType.ADMIN_CONTROL_ACTION,
            metadata={
                "action": "safety-mode-persist-failed",
                "error": str(exc)[:300],
            },
        )
    except Exception:  # noqa: BLE001 - 留痕失败不能反过来影响刹车
        logger.warning("safety_mode_persist_failure_not_recorded")


async def set_runtime_safety_mode_persisted(
    *,
    enabled: bool,
    reason: str | None = None,
    actor_id: str | None = None,
) -> RuntimeSafetyModeState:
    """改开关 + 落库。路由与自动刹车都走这个。"""
    state = set_runtime_safety_mode(enabled=enabled, reason=reason, actor_id=actor_id)
    await persist_runtime_safety_mode()
    return state


async def set_runtime_operational_pauses_persisted(
    *,
    pause_new_lock: bool,
    pause_new_authorization: bool,
    pause_new_task: bool,
    pause_new_settlement: bool,
    reason: str | None = None,
    actor_id: str | None = None,
) -> RuntimeSafetyModeState:
    """改运维暂停 + 落库。"""
    state = set_runtime_operational_pauses(
        pause_new_lock=pause_new_lock,
        pause_new_authorization=pause_new_authorization,
        pause_new_task=pause_new_task,
        pause_new_settlement=pause_new_settlement,
        reason=reason,
        actor_id=actor_id,
    )
    await persist_runtime_safety_mode()
    return state


async def hydrate_runtime_safety_mode() -> RuntimeSafetyModeState | None:
    """从库里读回开关，灌进内存缓存。

    库里还没有那一行（全新环境）= 什么都不做，保留本进程现值。
    内容与现值相同 = 不做无谓的写。
    """
    global _STATE
    try:
        factory = _session_factory()
        async with factory() as session:
            row = await session.get(RuntimeSafetyModeModel, _ROW_ID)
    except Exception as exc:  # noqa: BLE001 - 读不到不该拦住启动
        logger.warning("safety_mode_hydrate_failed", error=str(exc))
        return None
    if row is None:
        return None
    stored = _switch_of_row(row)
    if stored == _switch_of(_STATE):
        return None
    _STATE = _STATE.model_copy(update=stored)
    logger.info(
        "safety_mode_hydrated",
        enabled=_STATE.enabled,
        triggered_by=_STATE.triggered_by,
        pause_new_lock=_STATE.pause_new_lock,
    )
    return _STATE.model_copy()


async def run_refresher_forever(*, interval_seconds: float | None = None) -> None:
    """后台循环：每隔几秒把库里的开关灌回缓存。

    单 worker 下这层是冗余的（写是当场的）；它的价值在**多 worker**：别的进程
    改了开关，这里最多晚 ``interval`` 秒跟上，而不是永远只拦住 1/N。
    """
    interval = STATE_REFRESH_SECONDS if interval_seconds is None else float(interval_seconds)
    while True:
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        try:
            await hydrate_runtime_safety_mode()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 刷新失败不能杀死循环
            logger.warning("safety_mode_refresh_failed", error=str(exc))


async def audit_capacity_anchor_and_maybe_trip(
    db: AsyncSession,
    *,
    actor_id: str | None = "system",
) -> RuntimeSafetyModeState:
    result = await db.execute(
        select(
            func.coalesce(func.sum(CapacityModel.total_locked_usdc), 0.0),
            func.coalesce(func.sum(CapacityModel.total_bill_credits), 0.0),
        )
    )
    total_locked_usdc, total_bill_credits = result.one()
    now = datetime.utcnow()

    global _STATE
    _STATE = _STATE.model_copy(
        update={
            "last_anchor_audit_at": now,
            "total_locked_usdc": float(total_locked_usdc or 0.0),
            "total_bill_credits": float(total_bill_credits or 0.0),
        }
    )

    if _STATE.total_bill_credits > _STATE.total_locked_usdc + ANCHOR_EPSILON:
        # 落库而不是只改内存：这一跳往往正赶上「有人要去重启服务处理故障」，
        # 只留在内存里的话，重启之后刹车就没了。
        await set_runtime_safety_mode_persisted(
            enabled=True,
            reason=DEFAULT_ANCHOR_BREACH_REASON,
            actor_id=actor_id,
        )
        raise HTTPException(status_code=503, detail="safety mode enabled: capacity anchor breach detected")

    return _STATE.model_copy()
