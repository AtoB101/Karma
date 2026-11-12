"""并发安全的额度原子记账。

为什么需要这个模块（2026-09-17 并发实测）：

    15 个并发 ``POST /v1/capacity/{id}/lock`` 全部返回 200，
    但账上只增加了 1 笔（88 -> 98）。
    12 个并发 ``/release`` 同样：12 个 200，只减掉 1 笔。

根因是经典的「读 -> 改 -> 写」：多个请求各自读到同一份旧快照，
再各自整行写回，后写覆盖先写。全项目没有行锁（``with_for_update`` 0 处），
也没有乐观锁版本号，所以 PostgreSQL 生产环境同样会丢。

修法：把「校验 + 变更」压成**一条带守卫条件的 UPDATE**，
由数据库保证串行化 —— ``rowcount == 0`` 就表示守卫不成立
（余额不足、状态已被并发改变），调用方转成 409 即可。

注意：这里刻意只做「相对增量」（``col = col + delta``），
因为绝对赋值在并发下必然丢更新。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# 允许被原子加减的字段白名单，防住拼写错误导致的静默无效写入。
_BALANCE_FIELDS = frozenset(
    {
        "total_locked_usdc",
        "total_bill_credits",
        "available_credits",
        "reserved_credits",
        "in_progress_credits",
        "confirmed_progress_credits",
        "disputed_credits",
        "pending_settlement_credits",
        "burned_credits",
        "released_credits",
        "allocated_credits",
    }
)

Guard = Callable[[Any], Any]


class LedgerConflict(Exception):
    """原子更新没有命中：守卫条件不成立（余额不足 / 状态已变）。"""


def _validate_fields(deltas: Mapping[str, float]) -> None:
    unknown = [f for f in deltas if f not in _BALANCE_FIELDS]
    if unknown:
        raise ValueError(f"不允许原子变更的字段: {unknown}")
    for field, value in deltas.items():
        if not isinstance(value, (int, float)) or value != value:  # NaN 检查
            raise ValueError(f"{field} 的增量必须是有限数字，收到 {value!r}")


async def ensure_row(
    db: AsyncSession,
    model: Any,
    key_column: str,
    key: str,
    *,
    defaults: Mapping[str, Any] | None = None,
    extra_values: Mapping[str, Any] | None = None,
) -> None:
    """确保目标行存在（不存在则插入一条全 0 行）。

    并发插入同一主键时，另一路会先成功，这里吞掉 IntegrityError 并用 SAVEPOINT
    回滚到调用方的事务边界，避免把外层事务一起弄脏。
    """
    existing = await db.get(model, key)
    if existing is not None:
        return
    payload: dict[str, Any] = dict(defaults or {})
    payload.update(extra_values or {})
    payload[key_column] = key
    row = model(**payload)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        # 另一路已插入；继续走后面的原子 UPDATE。
        moved = await db.get(model, key)
        if moved is None:
            raise


async def apply_delta(
    db: AsyncSession,
    model: Any,
    key_column: str,
    key: str,
    deltas: Mapping[str, float],
    *,
    guards: Sequence[Guard] = (),
    extra_values: Mapping[str, Any] | None = None,
) -> int:
    """原子地把 ``deltas`` 加到目标行上；返回受影响行数（0 或 1）。"""
    _validate_fields(deltas)
    values: dict[str, Any] = {}
    for field, delta in deltas.items():
        column = getattr(model, field)
        values[field] = column + delta
    if extra_values:
        values.update(extra_values)
    if hasattr(model, "updated_at"):
        values["updated_at"] = datetime.utcnow()

    stmt = update(model).where(getattr(model, key_column) == key)
    for guard in guards:
        stmt = stmt.where(guard(model))
    stmt = stmt.values(**values)
    result = await db.execute(stmt)
    # ORM 身份映射里的旧对象必须失效，否则后面读回来还是旧快照。
    await db.flush()
    return int(result.rowcount or 0)


async def apply_delta_or_raise(
    db: AsyncSession,
    model: Any,
    key_column: str,
    key: str,
    deltas: Mapping[str, float],
    *,
    guards: Sequence[Guard] = (),
    extra_values: Mapping[str, Any] | None = None,
    message: str = "concurrent update conflict",
) -> None:
    rows = await apply_delta(
        db,
        model,
        key_column,
        key,
        deltas,
        guards=guards,
        extra_values=extra_values,
    )
    if rows != 1:
        raise LedgerConflict(message)


async def reload(db: AsyncSession, model: Any, key: str) -> Any | None:
    """取回目标行的**最新**快照（先让身份映射里的旧对象失效）。"""
    row = await db.get(model, key)
    if row is None:
        return None
    db.expire(row)
    await db.refresh(row)
    return row


# --------------------------------------------------------------------------
# capacity 专用守卫：把「并发期间责任额度没被动过」编码进 WHERE 条件，
# 这样「先读状态做业务判断、再写入」的两步操作也是安全的。
# --------------------------------------------------------------------------

RESPONSIBILITY_FIELDS = (
    "reserved_credits",
    "in_progress_credits",
    "confirmed_progress_credits",
    "disputed_credits",
    "pending_settlement_credits",
)


def responsibility_snapshot_guards(snapshot: Any) -> list[Guard]:
    """基于读到的快照生成等值守卫，任一责任额度被并发改动都会让写入落空。"""
    def _guard(field: str) -> Guard:
        expected = float(getattr(snapshot, field) or 0.0)

        def _check(model: Any) -> Any:
            return getattr(model, field) == expected

        return _check

    return [_guard(f) for f in RESPONSIBILITY_FIELDS]
