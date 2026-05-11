"""
Karma — Redis Receipt Store
Hot-path cache: receipts written here first, flushed to PostgreSQL async.
"""
from __future__ import annotations

import json
from typing import Optional

import redis.asyncio as aioredis

from config.settings import settings
from core.hooks.hook_layer import ReceiptStore
from core.schemas import ExecutionReceipt, ToolStatus

RECEIPT_TTL = 60 * 60 * 24 * 7  # 7 days


class RedisReceiptStore(ReceiptStore):
    """
    Stores receipts in Redis for fast lookup during active task execution.
    Use alongside PostgresReceiptStore: Redis for hot path, Postgres for durability.
    """

    def __init__(self, redis_client: aioredis.Redis):
        self._r = redis_client

    @classmethod
    async def create(cls) -> "RedisReceiptStore":
        r = await aioredis.from_url(settings.redis_url, decode_responses=True)
        return cls(r)

    async def save(self, receipt: ExecutionReceipt) -> None:
        data = receipt.model_dump(mode="json")
        pipe = self._r.pipeline()
        # Store individual receipt
        pipe.setex(
            f"receipt:{receipt.receipt_id}",
            RECEIPT_TTL,
            json.dumps(data),
        )
        # Add to task index (sorted set by step_index)
        pipe.zadd(
            f"task_receipts:{receipt.task_id}",
            {receipt.receipt_id: receipt.step_index},
        )
        pipe.expire(f"task_receipts:{receipt.task_id}", RECEIPT_TTL)
        await pipe.execute()

    async def get(self, receipt_id: str) -> Optional[ExecutionReceipt]:
        raw = await self._r.get(f"receipt:{receipt_id}")
        if not raw:
            return None
        return self._deserialize(json.loads(raw))

    async def list_by_task(self, task_id: str) -> list[ExecutionReceipt]:
        # Get all receipt IDs sorted by step_index
        receipt_ids = await self._r.zrange(f"task_receipts:{task_id}", 0, -1)
        if not receipt_ids:
            return []

        pipe = self._r.pipeline()
        for rid in receipt_ids:
            pipe.get(f"receipt:{rid}")
        results = await pipe.execute()

        receipts = []
        for raw in results:
            if raw:
                receipts.append(self._deserialize(json.loads(raw)))
        return sorted(receipts, key=lambda r: r.step_index)

    async def delete_task(self, task_id: str) -> None:
        receipt_ids = await self._r.zrange(f"task_receipts:{task_id}", 0, -1)
        if receipt_ids:
            pipe = self._r.pipeline()
            for rid in receipt_ids:
                pipe.delete(f"receipt:{rid}")
            pipe.delete(f"task_receipts:{task_id}")
            await pipe.execute()

    @staticmethod
    def _deserialize(data: dict) -> ExecutionReceipt:
        data["status"] = ToolStatus(data["status"])
        return ExecutionReceipt(**data)


class CachingReceiptStore(ReceiptStore):
    """
    Write-through store: writes to both Redis (fast) and Postgres (durable).
    Reads from Redis first, falls back to Postgres.
    """

    def __init__(self, redis_store: RedisReceiptStore, pg_store: ReceiptStore):
        self._redis = redis_store
        self._pg = pg_store

    async def save(self, receipt: ExecutionReceipt) -> None:
        await self._redis.save(receipt)
        await self._pg.save(receipt)

    async def get(self, receipt_id: str) -> Optional[ExecutionReceipt]:
        cached = await self._redis.get(receipt_id)
        if cached:
            return cached
        return await self._pg.get(receipt_id)

    async def list_by_task(self, task_id: str) -> list[ExecutionReceipt]:
        cached = await self._redis.list_by_task(task_id)
        if cached:
            return cached
        return await self._pg.list_by_task(task_id)
