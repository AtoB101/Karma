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


# --- 2026-09-30：验证过的 agent 钥匙也要有自己的读额度桶 -----------------------
#
# 实测背景：压测机（一个出口 IP）上跑的 agent 用的是**铸出来**的 agent 钥匙，而
# rate_limit_bucket 只认 AUTH_API_KEYS 里的静态钥匙，于是所有 agent 一起挤 ip: 桶，
# 轮询 settlement 时成片 429。口径跟写路径那次一样：验过的钥匙 -> 自己的桶。


@pytest.fixture()
def minted_store(tmp_path, monkeypatch):
    """把铸钥匙的落盘位置挪到 tmp，别碰仓库里的 .karma_data。"""
    from services import agent_bootstrap_credentials as abc

    monkeypatch.setattr(abc, "_STORE_PATH", tmp_path / "agent_api_keys.json")
    monkeypatch.setattr(abc, "_LOADED", False)
    monkeypatch.setattr(abc, "_KEYS", {})
    yield abc
    monkeypatch.setattr(abc, "_LOADED", False)
    monkeypatch.setattr(abc, "_KEYS", {})


def _api_key_request(key: str, peer: str = PEER) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/settlement/anything",
            "headers": [(b"x-karma-api-key", key.encode())],
            "client": (peer, 12345),
        },
        _empty_receive,
    )


def test_a_minted_agent_key_gets_its_own_bucket(minted_store):
    minted_store._ensure_loaded()
    key = minted_store.mint_agent_api_key("agent-readbucket1")["api_key"]

    bucket = rl.rate_limit_bucket(_api_key_request(key))
    assert bucket.startswith("ak:"), bucket
    assert key not in bucket

    other = minted_store.mint_agent_api_key("agent-readbucket2")["api_key"]
    assert rl.rate_limit_bucket(_api_key_request(other)) != bucket


def test_an_invented_key_still_falls_back_to_the_ip_bucket(minted_store):
    """形状像钥匙但没铸过：只能按 IP 算，编没有收益。"""
    minted_store._ensure_loaded()
    minted_store.mint_agent_api_key("agent-readbucket3")

    faked = "karma_agent-readbucket3_" + "z" * 24
    assert rl.rate_limit_bucket(_api_key_request(faked)) == "ip:" + PEER
    assert rl.rate_limit_bucket(_api_key_request("not-a-key")) == "ip:" + PEER


def test_a_configured_key_still_gets_its_own_bucket(minted_store, monkeypatch):
    monkeypatch.setattr(
        rl.settings, "auth_api_keys", "ops:ops-secret-of-sufficient-length", raising=False
    )
    bucket = rl.rate_limit_bucket(_api_key_request("ops-secret-of-sufficient-length"))
    assert bucket.startswith("ak:"), bucket


@pytest.mark.asyncio
async def test_two_minted_keys_behind_one_ip_do_not_share_the_read_budget(
    minted_store, no_redis, monkeypatch
):
    minted_store._ensure_loaded()
    monkeypatch.setitem(rl.RATE_LIMITS, "read", (2, 60))
    key_a = minted_store.mint_agent_api_key("agent-readbudget1")["api_key"]
    key_b = minted_store.mint_agent_api_key("agent-readbudget2")["api_key"]

    req_a = _api_key_request(key_a)
    req_b = _api_key_request(key_b)

    for _ in range(2):
        await rl.rate_limit(req_a, "read")
    with pytest.raises(HTTPException) as exc:
        await rl.rate_limit(req_a, "read")
    assert exc.value.status_code == 429

    # 同一个出口 IP、另一把（同样验过的）钥匙：额度是自己的。
    await rl.rate_limit(req_b, "read")
    await rl.rate_limit(req_b, "read")
