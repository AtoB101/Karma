"""Runtime Key 的 nonce 台账：重放保护 + 幂等回放。

口径见 ``db/models/orm.py`` 的 ``RuntimeNonceLogModel``。三个要点：

1. **占位立刻提交**。重放保护要跨进程生效，就不能等请求事务结束才可见 —— 一个
   place-order 可能跑十几秒，还可能被 nginx 超时切断。所以占位那一笔必须当场
   ``commit``；调用点因此都放在**任何业务写库之前**（权限校验之后第一句），
   commit 时手里没有别的半截写入。
2. **一次请求一行**：先占 ``in_flight``，跑完写 ``done`` 并把第一次的响应一起存下来。
   客户端拿到 504 之后重发，拿到的是上一次的真实结果（带 ``idempotent_replay`` 标记），
   而不是一句 409 duplicate —— 那等于逼调用方在「可能重复花钱」和「不敢重发」之间猜。
3. **死掉的占位可以被接手**：占位行超过 ``STALE_IN_FLIGHT_SECONDS`` 还停在 ``in_flight``
   （进程被重启、请求半路夭折），下一个同 nonce 的请求直接接手重跑。钱的路不能因为
   一次崩溃就把这个 nonce 永久锁死。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

import structlog
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import RuntimeNonceLogModel

logger = structlog.get_logger(__name__)

#: 占位多久算「上一次尝试已经死了」，可以被下一个同 nonce 的请求接手。
STALE_IN_FLIGHT_SECONDS = 120.0

#: 台账保留多久。nonce 的防重放窗口是分钟级，留一周足够复盘，也不会无限长。
PURGE_AFTER_SECONDS = 7 * 24 * 3600

#: 存响应体的上限：只用来幂等回放，不该把一张表撑爆。
MAX_PAYLOAD_CHARS = 200_000


def request_fingerprint(body: Any) -> str:
    """请求体摘要：用来分辨「同一个 nonce 重发」和「同一个 nonce 换了请求体」。

    后者是客户端 bug（拿错了 nonce）或者有人在试探，必须拒；前者才是幂等回放。
    """
    if hasattr(body, "model_dump"):
        body = body.model_dump(mode="json")
    try:
        raw = json.dumps(body, sort_keys=True, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        raw = str(body)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _find(
    db: AsyncSession, *, key_id: str, endpoint: str, nonce: str
) -> RuntimeNonceLogModel | None:
    res = await db.execute(
        select(RuntimeNonceLogModel).where(
            RuntimeNonceLogModel.key_id == key_id,
            RuntimeNonceLogModel.endpoint == endpoint,
            RuntimeNonceLogModel.nonce == nonce,
        )
    )
    return res.scalars().first()


async def claim(
    db: AsyncSession, *, key_id: str, endpoint: str, nonce: str, request_hash: str
) -> dict[str, Any]:
    """占住这个 nonce，返回该怎么处理这次请求。

    * ``new``      —— 没有先例，正常执行；
    * ``replay``   —— 上一次已经成功，原样回放它的响应；
    * ``busy``     —— 上一次还在跑，别插队（调用方回 409 + 重试提示）；
    * ``conflict`` —— 同一个 nonce 配了不同的请求体，拒。

    注意：这个方法会 ``commit`` 当前会话（占位必须立刻可见），所以调用方必须在
    任何业务写库**之前**调它。
    """
    key_id = str(key_id or "").strip()
    endpoint = str(endpoint or "").strip()[:64]
    nonce = str(nonce or "").strip()
    if not nonce or len(nonce) > 128:
        raise HTTPException(status_code=400, detail="client_nonce is required (max 128 chars)")
    now = datetime.utcnow()

    row = await _find(db, key_id=key_id, endpoint=endpoint, nonce=nonce)
    if row is None:
        if await _insert(
            db, key_id=key_id, endpoint=endpoint, nonce=nonce,
            request_hash=request_hash, now=now,
        ):
            return {"state": "new"}
        # 另一个进程同时插了同一行：读它，按它的状态决定。
        row = await _find(db, key_id=key_id, endpoint=endpoint, nonce=nonce)
        if row is None:
            return {"state": "busy"}
    return await _verdict(db, row=row, request_hash=request_hash, now=now)


async def _insert(
    db: AsyncSession, *, key_id: str, endpoint: str, nonce: str,
    request_hash: str, now: datetime,
) -> bool:
    try:
        async with db.begin_nested():
            db.add(
                RuntimeNonceLogModel(
                    key_id=key_id,
                    endpoint=endpoint,
                    nonce=nonce,
                    request_hash=request_hash or "",
                    state="in_flight",
                    created_at=now,
                    updated_at=now,
                )
            )
            await db.flush()
    except IntegrityError:
        return False
    await _purge(db, now=now)
    await db.commit()
    return True


async def _purge(db: AsyncSession, *, now: datetime) -> None:
    cutoff = now - timedelta(seconds=PURGE_AFTER_SECONDS)
    try:
        await db.execute(
            delete(RuntimeNonceLogModel).where(RuntimeNonceLogModel.created_at < cutoff)
        )
    except Exception as exc:  # noqa: BLE001 - 清理失败不该影响这次请求
        logger.warning("runtime_nonce_purge_failed", error=str(exc))


async def _verdict(
    db: AsyncSession, *, row: RuntimeNonceLogModel, request_hash: str, now: datetime
) -> dict[str, Any]:
    # 同一个 nonce 换了请求体：不管这条 nonce 还在飞、还是已经 done，都是客户端错。
    # 一律 409，绝不把上一个请求的结果当成这个请求的回放。
    if row.request_hash and request_hash and row.request_hash != request_hash:
        return {"state": "conflict"}
    if row.state == "done":
        try:
            payload = json.loads(row.payload or "{}")
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {"result": payload}
        return {
            "state": "replay",
            "http_status": int(row.http_status or 200),
            "payload": payload,
        }
    age = (now - (row.created_at or now)).total_seconds()
    if age <= STALE_IN_FLIGHT_SECONDS:
        return {"state": "busy", "age_seconds": round(age, 1)}
    # 上一次尝试早就死了（进程重启 / 请求夭折）：接手这个 nonce，别把它永久锁死。
    row.request_hash = request_hash or row.request_hash
    row.created_at = now
    row.updated_at = now
    row.state = "in_flight"
    row.http_status = None
    row.payload = None
    await db.commit()
    return {"state": "new", "took_over": True}


async def complete(
    db: AsyncSession, *, key_id: str, endpoint: str, nonce: str, http_status: int, payload: Any
) -> None:
    """记下这次成功的结果，供同 nonce 的重发原样回放。

    写不进去只记日志：能不能花钱由权限、额度和服务端状态决定，不由这张表决定。
    """
    key_id = str(key_id or "").strip()
    endpoint = str(endpoint or "").strip()[:64]
    nonce = str(nonce or "").strip()
    if not nonce:
        return
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = json.dumps({"result": str(payload)}, ensure_ascii=False)
    try:
        row = await _find(db, key_id=key_id, endpoint=endpoint, nonce=nonce)
        if row is None:
            return
        row.state = "done"
        row.http_status = int(http_status)
        row.payload = text[:MAX_PAYLOAD_CHARS]
        row.updated_at = datetime.utcnow()
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - 台账写不进绝不影响这次请求
        logger.warning(
            "runtime_nonce_complete_failed", key_id=key_id, endpoint=endpoint, error=str(exc)
        )


async def forget(db: AsyncSession, *, key_id: str, endpoint: str, nonce: str) -> None:
    """忘掉这个 nonce（第一次执行彻底失败、客户端应当能重试时用）。"""
    key_id = str(key_id or "").strip()
    endpoint = str(endpoint or "").strip()[:64]
    nonce = str(nonce or "").strip()
    if not nonce:
        return
    try:
        await db.execute(
            delete(RuntimeNonceLogModel).where(
                RuntimeNonceLogModel.key_id == key_id,
                RuntimeNonceLogModel.endpoint == endpoint,
                RuntimeNonceLogModel.nonce == nonce,
            )
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "runtime_nonce_forget_failed", key_id=key_id, endpoint=endpoint, error=str(exc)
        )
