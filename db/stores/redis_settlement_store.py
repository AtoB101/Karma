"""
Karma — Redis Settlement State Cache
Fast state reads during active task lifecycle.
"""
from __future__ import annotations

import json
from typing import Optional

import redis.asyncio as aioredis

from config.settings import settings
from core.schemas import SettlementState, TaskStatus
from core.settlement.engine import SettlementStore

STATE_TTL = 60 * 60 * 24 * 30  # 30 days


class RedisSettlementStore(SettlementStore):

    def __init__(self, redis_client: aioredis.Redis):
        self._r = redis_client

    @classmethod
    async def create(cls) -> "RedisSettlementStore":
        r = await aioredis.from_url(settings.redis_url, decode_responses=True)
        return cls(r)

    async def save(self, state: SettlementState) -> None:
        data = state.model_dump(mode="json")
        pipe = self._r.pipeline()
        pipe.setex(f"settlement:{state.task_id}", STATE_TTL, json.dumps(data))
        pipe.sadd(f"settlements_by_status:{state.status}", state.task_id)
        await pipe.execute()

    async def get(self, task_id: str) -> Optional[SettlementState]:
        raw = await self._r.get(f"settlement:{task_id}")
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
