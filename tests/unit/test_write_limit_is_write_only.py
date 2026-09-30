"""写档位只该被写请求吃掉（2026-09-30 并发压测抓到的）。

路由是**按前缀**挂依赖的（api/app.py）：``/v1/settlement`` 上既挂着
``GET /v1/settlement/{task_id}``（轮询结算，一单要轮几十次），也挂着
``POST /v1/settlement/{task_id}/buyer-accept``，两者共用同一个
``Depends(make_rate_limit_dep("write_sensitive"))``。于是 10 路并发轮询 =
120 次/60s 直接把写档的 100/60s 顶穿，轮询成片 429 —— 读被按写收费了。

口径：读有 read 档（``read_rate_limit_middleware``，``/v1/*`` 的 GET/HEAD，
600/60s）兜底，写档只收写。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.middleware import rate_limit as rl

PEER = "203.0.113.77"


def _request(method: str, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "client": (PEER, 12345),
            "query_string": b"",
        }
    )


@pytest.fixture(autouse=True)
def _fresh_windows():
    rl.clear_memory_rate_limits()
    yield
    rl.clear_memory_rate_limits()


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.asyncio
async def test_reads_do_not_consume_a_write_scoped_dep(method, monkeypatch):
    """轮询结算再有几十发，也不该把写额度耗掉。"""
    monkeypatch.setitem(rl.RATE_LIMITS, "write_sensitive", (1, 60))
    dep = rl.make_rate_limit_dep("write_sensitive")

    for _ in range(5):
        await dep(_request(method, "/v1/settlement/abc"))


@pytest.mark.asyncio
async def test_writes_still_consume_the_write_scoped_dep(monkeypatch):
    monkeypatch.setitem(rl.RATE_LIMITS, "write_sensitive", (1, 60))
    dep = rl.make_rate_limit_dep("write_sensitive")

    await dep(_request("POST", "/v1/settlement/abc/buyer-accept"))
    with pytest.raises(HTTPException) as exc:
        await dep(_request("POST", "/v1/settlement/abc/buyer-accept"))
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_state_transition_dep_is_write_only_too(monkeypatch):
    monkeypatch.setitem(rl.RATE_LIMITS, "state_transition", (1, 60))
    dep = rl.make_rate_limit_dep("state_transition")

    await dep(_request("GET", "/v1/capacity/abc"))
    await dep(_request("GET", "/v1/capacity/abc"))
    await dep(_request("POST", "/v1/capacity/abc/lock"))
    with pytest.raises(HTTPException) as exc:
        await dep(_request("POST", "/v1/capacity/abc/lock"))
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_non_write_keys_keep_metering_every_method(monkeypatch):
    """read/default 这些不是写档，别被方法判断误伤。"""
    monkeypatch.setitem(rl.RATE_LIMITS, "default", (1, 60))
    dep = rl.make_rate_limit_dep("default")

    await dep(_request("GET", "/v1/info"))
    with pytest.raises(HTTPException) as exc:
        await dep(_request("GET", "/v1/info"))
    assert exc.value.status_code == 429
