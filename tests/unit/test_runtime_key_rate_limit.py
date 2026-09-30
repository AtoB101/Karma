"""runtime key 要参与限流分桶（2026-09-30 并发压测抓到的）。

背景：``rate_limit_bucket`` 只给**已配置的** ``X-Karma-Api-Key`` 开专属桶，其余一律落到
``ip:<real_client_ip>``。于是同一台机器上跑的多个 agent（同一个出口 IP）会互相挤占同一个
20/60s 桶，而且 429 重试本身也在填桶 —— 越试越出不来（实测：5 个 agent 从同一出口 IP
并发下单，交付回执全部被卡死）。

口径：中间件跑在鉴权之前，只认得了 socket peer，所以那一层退成**不可伪造的粗兜底**；
真正紧的额度在 ``get_runtime_context`` **验签通过之后**按 runtime key 判。
"""
from __future__ import annotations

import types

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.middleware import rate_limit as rl
from api.routes import runtime_gateway as gw
from config.settings import settings

PEER = "203.0.113.9"


@pytest.fixture()
def no_redis(monkeypatch):
    """强制走进程内兜底，计数才是确定的。"""

    async def _boom():
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(rl, "get_redis", _boom)
    monkeypatch.setattr(settings, "rate_limit_redis_fail_closed", False)


async def _empty_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def _request(
    path: str = "/runtime/place-order", peer: str = PEER, method: str = "POST"
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "client": (peer, 12345),
        },
        _empty_receive,
    )


def test_path_classification_is_shared_with_the_middleware():
    """网关和中间件必须用同一份「哪条算状态机写」的规则，否则两边额度会漂。"""
    from api.app import _is_state_transition_write

    assert rl.write_limit_key_for_path("/runtime/place-order") == "write_sensitive"
    assert rl.write_limit_key_for_path("/runtime/submit-receipt") == "state_transition"
    assert rl.write_limit_key_for_path("/runtime/submit-bundle") == "state_transition"
    assert rl.write_limit_key_for_path("/v1/capacity/lock") == "state_transition"
    for path in (
        "/runtime/place-order",
        "/runtime/submit-receipt",
        "/v1/settlement/submit",
        "/v1/vouchers/abc/accept",
    ):
        assert _is_state_transition_write(path) == rl.is_state_transition_write(path)


def test_runtime_key_bucket_never_carries_the_plaintext_token():
    token = "KRM_RT_" + "a" * 40
    bucket = rl.runtime_key_bucket(token)
    assert bucket.startswith("rk:")
    assert token not in bucket
    assert rl.runtime_key_bucket(token) == rl.runtime_key_bucket(token)
    assert rl.runtime_key_bucket(token) != rl.runtime_key_bucket(token + "x")


@pytest.mark.asyncio
async def test_two_keys_behind_one_ip_do_not_share_the_budget(no_redis, monkeypatch):
    monkeypatch.setitem(rl.RATE_LIMITS, "state_transition", (2, 60))
    req = _request()
    key_a = rl.runtime_key_bucket("KRM_RT_key_a")
    key_b = rl.runtime_key_bucket("KRM_RT_key_b")

    for _ in range(2):
        await rl.rate_limit(req, "state_transition", bucket=key_a)
    with pytest.raises(HTTPException) as exc:
        await rl.rate_limit(req, "state_transition", bucket=key_a)
    assert exc.value.status_code == 429

    # 同一个 socket peer、另一把钥匙：额度是自己的，不该被邻居拖累。
    await rl.rate_limit(req, "state_transition", bucket=key_b)
    await rl.rate_limit(req, "state_transition", bucket=key_b)


@pytest.mark.asyncio
async def test_one_key_behind_two_ips_still_shares_the_budget(no_redis, monkeypatch):
    """按 key 分桶的另一半意思：换出口 IP 也逃不掉自己那把钥匙的额度。"""
    monkeypatch.setitem(rl.RATE_LIMITS, "state_transition", (2, 60))
    bucket = rl.runtime_key_bucket("KRM_RT_roamer")

    await rl.rate_limit(_request(peer="198.51.100.1"), "state_transition", bucket=bucket)
    await rl.rate_limit(_request(peer="198.51.100.2"), "state_transition", bucket=bucket)
    with pytest.raises(HTTPException) as exc:
        await rl.rate_limit(_request(peer="198.51.100.3"), "state_transition", bucket=bucket)
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_gateway_limits_by_key_after_verifying_the_signature(no_redis, monkeypatch):
    """验签通过之后那一层：同一 IP 的两把钥匙各有各的额度。"""
    # /runtime/place-order 走 write_sensitive 档（只有 /submit* 那些才是 20/60s 的紧档）。
    monkeypatch.setitem(rl.RATE_LIMITS, "write_sensitive", (3, 60))

    async def fake_load(db, token):
        return types.SimpleNamespace(
            key_id="kid-" + token, key_binding="service", agent_public_key=None
        )

    monkeypatch.setattr(gw, "load_active_context", fake_load)
    monkeypatch.setattr(gw, "verify_signed_request", lambda **kw: None)

    async def call(token: str) -> None:
        await gw.get_runtime_context(request=_request(), db=None, x_karma_runtime_key=token)

    for _ in range(3):
        await call("KRM_RT_aaa")
    with pytest.raises(HTTPException) as exc:
        await call("KRM_RT_aaa")
    assert exc.value.status_code == 429
    assert "Rate limit exceeded" in str(exc.value.detail)

    # 同一台机器（同一个 IP）上的另一把钥匙：照常放行。
    await call("KRM_RT_bbb")


@pytest.mark.asyncio
async def test_gateway_does_not_charge_read_paths_to_the_write_budget(no_redis, monkeypatch):
    monkeypatch.setitem(rl.RATE_LIMITS, "write_sensitive", (1, 60))

    async def fake_load(db, token):
        return types.SimpleNamespace(
            key_id="kid-" + token, key_binding="service", agent_public_key=None
        )

    monkeypatch.setattr(gw, "load_active_context", fake_load)
    monkeypatch.setattr(gw, "verify_signed_request", lambda **kw: None)

    async def call(path: str, method: str = "POST") -> None:
        await gw.get_runtime_context(
            request=_request(path=path, method=method),
            db=None,
            x_karma_runtime_key="KRM_RT_read",
        )

    await call("/runtime/place-order")
    with pytest.raises(HTTPException) as exc:
        await call("/runtime/place-order")
    assert exc.value.status_code == 429
    # GET（读）不进写额度，所以这一次不该 429。
    await call("/runtime/permissions", "GET")


@pytest.mark.asyncio
async def test_middleware_still_caps_unauthenticated_runtime_traffic_by_ip(
    client, monkeypatch
):
    """粗兜底还在：没验签就只能是「按 IP」的，这条路不能变成不限流。"""
    monkeypatch.setitem(rl.RATE_LIMITS, "runtime_preauth", (2, 60))

    for _ in range(2):
        await client.post("/runtime/place-order", json={"requirement_text": "x"})
    blocked = await client.post("/runtime/place-order", json={"requirement_text": "x"})
    assert blocked.status_code == 429, blocked.text
    assert "Rate limit exceeded" in blocked.json()["detail"]
