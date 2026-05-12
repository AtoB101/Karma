"""
Karma — Redis Settlement State Cache
Fast state reads during active task lifecycle.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

import redis.asyncio as aioredis

from config.settings import settings
from core.schemas import SettlementState, TaskStatus
from core.settlement.engine import SettlementStore

STATE_TTL = 60 * 60 * 24 * 30  # 30 days
_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _safe_key_component(value: str) -> str:
    raw = (value or "").strip()
    if _SAFE_KEY_RE.match(raw) and len(raw) <= settings.redis_key_max_length:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"h:{digest[:32]}"


class RedisSettlementStore(SettlementStore):

    def __init__(self, redis_client: aioredis.Redis):
        self._r = redis_client

    @classmethod
    async def create(cls) -> "RedisSettlementStore":
        r = await aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=settings.redis_max_connections,
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
        )
        return cls(r)

    async def save(self, state: SettlementState) -> None:
        data = state.model_dump(mode="json")
        task_key = _safe_key_component(state.task_id)
        settlement_key = f"settlement:{task_key}"
        previous_raw = await self._r.get(settlement_key)
        pipe = self._r.pipeline()
        pipe.setex(settlement_key, STATE_TTL, json.dumps(data))
        if previous_raw:
            previous_state = json.loads(previous_raw)
            previous_status = previous_state.get("status")
            if previous_status:
                pipe.srem(f"settlements_by_status:{previous_status}", task_key)
        pipe.sadd(f"settlements_by_status:{state.status.value}", task_key)
        pipe.expire(f"settlements_by_status:{state.status.value}", STATE_TTL)
        await pipe.execute()

    async def get(self, task_id: str) -> Optional[SettlementState]:
        task_key = _safe_key_component(task_id)
        raw = await self._r.get(f"settlement:{task_key}")
        if not raw:
            return None
        data = json.loads(raw)
        data["status"] = TaskStatus(data["status"])
        return SettlementState(**data)

    async def list_by_status(self, status: TaskStatus) -> list[SettlementState]:
        task_ids = await self._r.smembers(f"settlements_by_status:{status.value}")
        results = []
        for tid in task_ids:
            s = await self.get(tid)
            if s:
                results.append(s)
        return results
