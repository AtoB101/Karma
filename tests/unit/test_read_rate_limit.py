"""读接口限流（P2-11）。

2026-09-17 复核：只有 ``/v1/auth/token``、``/v1/verify`` 和
``SENSITIVE_WRITE_PREFIXES`` 里的**写**操作有限流，``GET /v1/*`` 基本没有 ——
任何脚本都能不限速地枚举接口。这里锁住「读也有一档兜底额度」。
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from api.middleware import rate_limit as rate_limit_module


@pytest.mark.asyncio
async def test_reads_are_rate_limited(client: AsyncClient, monkeypatch):
    monkeypatch.setitem(rate_limit_module.RATE_LIMITS, "read", (3, 60))

    for _ in range(3):
        ok = await client.get("/v1/info")
        assert ok.status_code == 200, ok.text

    blocked = await client.get("/v1/info")
    assert blocked.status_code == 429, blocked.text
    assert "Rate limit exceeded" in blocked.json()["detail"]


@pytest.mark.asyncio
async def test_writes_are_not_charged_to_the_read_bucket(client: AsyncClient, monkeypatch):
    """写请求走自己的档位，不该把读额度吃掉。"""
    monkeypatch.setitem(rate_limit_module.RATE_LIMITS, "read", (2, 60))

    first = await client.get("/v1/info")
    assert first.status_code == 200
    # 中间夹一个写请求（容量锁定），读额度不应被它消耗。
    await client.post("/v1/capacity/rate-limit-probe/lock", json={"amount": 5})
    second = await client.get("/v1/info")
    assert second.status_code == 200
    third = await client.get("/v1/info")
    assert third.status_code == 429
