"""Runtime Key 使用时刻硬校验：agent 公钥绑定 + 逐请求验签。

这一层解决的是「key 是 bearer 令牌，被偷走就等于被花掉」：
绑定之后光有 key 字符串不够，每个请求都要有对应私钥签出来的签名。

同时钉住两件容易悄悄漂移的事：
* 服务端与 SDK 的签名消息格式必须逐字一致（两边各写一份，这里比对）；
* 没绑公钥的老 key 行为与升级前完全一致（不能把已经在跑的 agent 打掉）。
"""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient

from services import runtime_key_service as rks
from services.runtime_wallet import build_agent_request_message, build_create_key_message
from sdk.runtime_client import (
    agent_key_from_seed,
    build_agent_request_message as sdk_build_agent_request_message,
    runtime_key_id,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fake_ctx(public_key: str, *, permissions: list[str] | None = None) -> rks.RuntimeKeyContext:
    return rks.RuntimeKeyContext(
        key_id="a" * 32,
        karma_identity_id="kid_signing_test",
        profile_id=None,
        wallet_address="0x" + "1" * 40,
        permissions=list(permissions or []),
        single_limit=10.0,
        daily_limit=100.0,
        expire_at=datetime.now(timezone.utc) + timedelta(days=7),
        agent_name="signer",
        status="active",
        key_binding="agent" if public_key else "service",
        agent_public_key=public_key or None,
        nonce_required=rks.is_nonce_required(permissions or []),
    )


def _sign(key, message: str) -> str:
    return base64.b64encode(key.sign(message.encode("utf-8"))).decode()


# ---------------------------------------------------------------- 消息格式


def test_sdk_and_server_agree_on_the_signed_message():
    """SDK 是独立分发的，签名消息在两边各写了一份 —— 必须逐字相同。"""
    kwargs = dict(
        key_id="f" * 32,
        method="post",
        path="/runtime/place-order",
        timestamp="2026-09-18T12:00:00Z",
        nonce="nonce-12345678",
        body_sha256=hashlib.sha256(b'{"a":1}').hexdigest(),
    )
    assert build_agent_request_message(**kwargs) == sdk_build_agent_request_message(**kwargs)
    server = build_agent_request_message(**kwargs)
    assert server.startswith("Karma Runtime Request\n")
    assert "\nmethod:POST\n" in server  # 方法一律大写
    assert "\npath:/runtime/place-order\n" in server


def test_runtime_key_id_matches_the_token_body():
    assert runtime_key_id("KRM_RT_" + "b" * 32 + "_" + "c" * 64) == "b" * 32
    assert runtime_key_id("nonsense") == ""


# ---------------------------------------------------------------- 公钥

def test_agent_public_key_accepts_base64_and_hex_only():
    key = agent_key_from_seed(base64.b64encode(bytes(range(32))).decode())
    from cryptography.hazmat.primitives import serialization

    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    b64 = base64.b64encode(raw).decode()
    assert rks.normalize_agent_public_key(b64) == b64
    assert rks.normalize_agent_public_key(raw.hex()) == b64
    assert rks.normalize_agent_public_key("0x" + raw.hex()) == b64
    with pytest.raises(rks.PublicKeyError):
        rks.normalize_agent_public_key("")
    with pytest.raises(rks.PublicKeyError):
        rks.normalize_agent_public_key(base64.b64encode(b"too-short").decode())


def test_agent_public_key_accepts_the_seed_hex_the_sdk_expects():
    """SDK 允许私钥写成 hex 或 base64；两种写法推出来的公钥必须一样。"""
    seed = bytes(range(32))
    from cryptography.hazmat.primitives import serialization

    raw = agent_key_from_seed(seed.hex()).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    expected = base64.b64encode(raw).decode()
    assert (
        agent_key_from_seed(base64.b64encode(seed).decode()).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        == raw
    )
    assert rks.normalize_agent_public_key(expected) == expected


def test_fingerprint_is_stable_and_short():
    key = agent_key_from_seed(base64.b64encode(b"\x07" * 32 + b"\x00" * 0).decode())
    from cryptography.hazmat.primitives import serialization

    pub = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    fp = rks.agent_binding_fingerprint(pub)
    assert len(fp) == 32 and fp == rks.agent_binding_fingerprint(pub)


# ---------------------------------------------------------------- 有效期 / nonce 策略

def test_key_lifetime_is_capped():
    ok = datetime.now(timezone.utc) + timedelta(days=30)
    assert rks.assert_key_lifetime_sane(ok) == ok
    ten_years = datetime.now(timezone.utc) + timedelta(days=3650)
    with pytest.raises(Exception) as exc:
        rks.assert_key_lifetime_sane(ten_years)
    assert str(rks.MAX_KEY_LIFETIME_DAYS) in str(getattr(exc.value, "detail", exc.value))
    with pytest.raises(Exception):
        rks.assert_key_lifetime_sane(datetime.now(timezone.utc) - timedelta(seconds=5))


def test_nonce_required_only_for_money_moving_permissions():
    assert rks.is_nonce_required(["place_order"]) is True
    assert rks.is_nonce_required(["request_settlement", "sync_task_status"]) is True
    assert rks.is_nonce_required(["discover_agents", "submit_receipt"]) is False


# ---------------------------------------------------------------- 验签

def test_signed_request_round_trip_and_failures():
    key = agent_key_from_seed(base64.b64encode(b"\x11" * 32).decode())
    from cryptography.hazmat.primitives import serialization

    pub = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    ctx = _fake_ctx(pub, permissions=["place_order"])
    body = b'{"client_nonce":"abcdefgh"}'
    ts, nonce = _now_iso(), uuid.uuid4().hex
    msg = build_agent_request_message(
        key_id=ctx.key_id,
        method="POST",
        path="/runtime/place-order",
        timestamp=ts,
        nonce=nonce,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
    ok = dict(
        ctx=ctx,
        method="POST",
        path="/runtime/place-order",
        body=body,
        signature_b64=_sign(key, msg),
        timestamp_header=ts,
        nonce_header=nonce,
    )
    rks.verify_signed_request(**ok)

    # 同一个 nonce 再来一次 → 重放
    with pytest.raises(Exception) as replay:
        rks.verify_signed_request(**ok)
    assert "nonce" in str(getattr(replay.value, "detail", replay.value))

    other = agent_key_from_seed(base64.b64encode(b"\x22" * 32).decode())
    bad = dict(ok, signature_b64=_sign(other, msg), nonce_header=uuid.uuid4().hex)
    with pytest.raises(Exception) as exc:
        rks.verify_signed_request(**bad)
    assert "signature" in str(getattr(exc.value, "detail", exc.value))

    # 签名有效但请求体被改过 → 摘要对不上
    tampered = dict(
        ok,
        body=b'{"client_nonce":"abcdefgh","amount":999}',
        nonce_header=uuid.uuid4().hex,
    )
    with pytest.raises(Exception):
        rks.verify_signed_request(**tampered)

    # 时间戳过期（重放窗口外）
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_msg = build_agent_request_message(
        key_id=ctx.key_id,
        method="POST",
        path="/runtime/place-order",
        timestamp=stale_ts,
        nonce=uuid.uuid4().hex,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
    with pytest.raises(Exception) as stale:
        rks.verify_signed_request(
            ctx=ctx,
            method="POST",
            path="/runtime/place-order",
            body=body,
            signature_b64=_sign(key, stale_msg),
            timestamp_header=stale_ts,
            nonce_header=uuid.uuid4().hex,
        )
    assert "window" in str(getattr(stale.value, "detail", stale.value))


def test_bound_key_refuses_a_request_without_a_signature():
    key = agent_key_from_seed(base64.b64encode(b"\x33" * 32).decode())
    from cryptography.hazmat.primitives import serialization

    pub = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    with pytest.raises(Exception) as exc:
        rks.verify_signed_request(
            ctx=_fake_ctx(pub),
            method="GET",
            path="/runtime/permissions",
            body=b"",
            signature_b64=None,
            timestamp_header=None,
            nonce_header=None,
        )
    assert "X-Karma-Agent-Signature" in str(getattr(exc.value, "detail", exc.value))


def test_unbound_key_keeps_working_without_a_signature():
    """老 key（没绑公钥）行为不变；带了签名则说明调用方搞错了对象。"""
    ctx = _fake_ctx("")
    rks.verify_signed_request(
        ctx=ctx,
        method="GET",
        path="/runtime/permissions",
        body=b"",
        signature_b64=None,
        timestamp_header=None,
        nonce_header=None,
    )
    with pytest.raises(Exception) as exc:
        rks.verify_signed_request(
            ctx=ctx,
            method="GET",
            path="/runtime/permissions",
            body=b"",
            signature_b64="c2ln",
            timestamp_header=_now_iso(),
            nonce_header=uuid.uuid4().hex,
        )
    assert "bind-key" in str(getattr(exc.value, "detail", exc.value))


# ---------------------------------------------------------------- 端到端

async def _mint(client: AsyncClient, *, identity: str, perms: list[str], agent_id: str, **kw):
    acct = Account.create()
    expire = kw.pop("expire", datetime.utcnow() + timedelta(days=7))
    msg = build_create_key_message(
        karma_identity_id=identity,
        wallet_address=acct.address,
        permissions=sorted(perms),
        single_limit=kw.pop("single_limit", 100.0),
        daily_limit=kw.pop("daily_limit", 500.0),
        expire_time=expire,
        agent_name="signing-test",
        agent_binding=agent_id or None,
    )
    body = {
        "wallet_address": acct.address,
        "karma_identity_id": identity,
        "wallet_signature": acct.sign_message(encode_defunct(text=msg)).signature.hex(),
        "permissions": sorted(perms),
        "single_limit": 100.0,
        "daily_limit": 500.0,
        "expire_time": expire.isoformat(),
        "agent_name": "signing-test",
        "agent_binding": agent_id or None,
        **kw,
    }
    return await client.post("/runtime/create-key", json=body)


def _headers_for(token: str, key, *, method: str, path: str, body: bytes, **over):
    ts = over.pop("timestamp", _now_iso())
    nonce = over.pop("nonce", uuid.uuid4().hex)
    message = build_agent_request_message(
        key_id=runtime_key_id(token),
        method=method,
        path=path,
        timestamp=ts,
        nonce=nonce,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
    headers = {
        "X-Karma-Runtime-Key": token,
        "X-Karma-Agent-Signature": _sign(key, message),
        "X-Karma-Runtime-Timestamp": ts,
        "X-Karma-Runtime-Nonce": nonce,
        "Content-Type": "application/json",
    }
    headers.update(over)
    return headers


@pytest.mark.asyncio
async def test_bind_key_then_every_request_must_be_signed(client: AsyncClient, db_session):
    identity = "kid-signing-e2e-1"
    agent_id = "agent-signing-e2e-1"
    minted = await _mint(client, identity=identity, perms=["sync_task_status"], agent_id=agent_id)
    assert minted.status_code == 201, minted.text
    data = minted.json()
    token = data["runtime_key"]
    assert data["key_binding"] == "service"  # 铸造时还没绑公钥
    assert data["binding_scope"].startswith("Karma Runtime Key Binding")
    assert data["binding_scope_signature"]

    # 绑定前：老路径，不带签名也能读
    pre = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": token})
    assert pre.status_code == 200
    assert pre.json()["key_binding"] == "service"

    agent_key = agent_key_from_seed(base64.b64encode(b"\x44" * 32).decode())
    from cryptography.hazmat.primitives import serialization

    pub = base64.b64encode(
        agent_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    bind_body = json.dumps(
        {"agent_id": agent_id, "agent_public_key": pub, "client_nonce": uuid.uuid4().hex}
    ).encode()
    bound = await client.post(
        "/runtime/bind-key",
        content=bind_body,
        headers={
            "X-Karma-Runtime-Key": token,
            "Content-Type": "application/json",
        },
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["key_binding"] == "agent"
    assert bound.json()["binding_scope_signature"]

    # 绑定后：不带签名一律 401
    unsigned = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": token})
    assert unsigned.status_code == 401
    assert "X-Karma-Agent-Signature" in unsigned.json()["detail"]

    signed = await client.get(
        "/runtime/permissions",
        headers=_headers_for(token, agent_key, method="GET", path="/runtime/permissions", body=b""),
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["key_binding"] == "agent"
    assert signed.json()["agent_fingerprint"]

    # 换一把私钥 → 验签不过
    intruder = agent_key_from_seed(base64.b64encode(b"\x55" * 32).decode())
    forged = await client.get(
        "/runtime/permissions",
        headers=_headers_for(token, intruder, method="GET", path="/runtime/permissions", body=b""),
    )
    assert forged.status_code == 401

    # 同一 nonce 重放 → 409
    nonce = uuid.uuid4().hex
    first = await client.get(
        "/runtime/permissions",
        headers=_headers_for(
            token, agent_key, method="GET", path="/runtime/permissions", body=b"", nonce=nonce
        ),
    )
    assert first.status_code == 200
    replay = await client.get(
        "/runtime/permissions",
        headers=_headers_for(
            token, agent_key, method="GET", path="/runtime/permissions", body=b"", nonce=nonce
        ),
    )
    assert replay.status_code == 409


@pytest.mark.asyncio
async def test_bind_key_rejects_a_key_minted_for_another_agent(client: AsyncClient, db_session):
    minted = await _mint(
        client, identity="kid-signing-e2e-2", perms=["sync_task_status"], agent_id="agent-owner-2"
    )
    token = minted.json()["runtime_key"]
    body = json.dumps(
        {
            "agent_id": "agent-someone-else",
            "agent_public_key": base64.b64encode(b"\x01" * 32).decode(),
            "client_nonce": uuid.uuid4().hex,
        }
    ).encode()
    resp = await client.post(
        "/runtime/bind-key",
        content=body,
        headers={"X-Karma-Runtime-Key": token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_key_rejects_an_agent_id_that_contradicts_the_signature(
    client: AsyncClient, db_session
):
    """agent_id 和 agent_binding 说的必须是同一件事，否则就是用户没授权过那个 agent。"""
    acct = Account.create()
    expire = datetime.utcnow() + timedelta(days=7)
    msg = build_create_key_message(
        karma_identity_id="kid-signing-e2e-3",
        wallet_address=acct.address,
        permissions=["sync_task_status"],
        single_limit=100.0,
        daily_limit=500.0,
        expire_time=expire,
        agent_name="signing-test",
        agent_binding="agent-a",
    )
    body = {
        "wallet_address": acct.address,
        "karma_identity_id": "kid-signing-e2e-3",
        "wallet_signature": acct.sign_message(encode_defunct(text=msg)).signature.hex(),
        "permissions": ["sync_task_status"],
        "single_limit": 100.0,
        "daily_limit": 500.0,
        "expire_time": expire.isoformat(),
        "agent_name": "signing-test",
        "agent_binding": "agent-a",
        "agent_id": "agent-b",
    }
    resp = await client.post("/runtime/create-key", json=body)
    assert resp.status_code == 403

    body_no_binding = dict(body)
    body_no_binding["agent_binding"] = None
    msg2 = build_create_key_message(
        karma_identity_id="kid-signing-e2e-3",
        wallet_address=acct.address,
        permissions=["sync_task_status"],
        single_limit=100.0,
        daily_limit=500.0,
        expire_time=expire,
        agent_name="signing-test",
        agent_binding=None,
    )
    body_no_binding["wallet_signature"] = acct.sign_message(
        encode_defunct(text=msg2)
    ).signature.hex()
    resp2 = await client.post("/runtime/create-key", json=body_no_binding)
    assert resp2.status_code == 400


@pytest.mark.asyncio
async def test_create_key_refuses_a_ten_year_key(client: AsyncClient, db_session):
    resp = await _mint(
        client,
        identity="kid-signing-e2e-4",
        perms=["sync_task_status"],
        agent_id="agent-4",
        expire=datetime.utcnow() + timedelta(days=3650),
    )
    assert resp.status_code == 400
    assert "90" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_unbound_keys_still_work_exactly_as_before(client: AsyncClient, db_session):
    """升级不能把已经在跑的 agent 打掉：没绑公钥的 key 只认 key 本身。"""
    minted = await _mint(client, identity="kid-signing-e2e-5", perms=["sync_task_status"], agent_id="")
    token = minted.json()["runtime_key"]
    resp = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["key_binding"] == "service"
    assert body["agent_fingerprint"] == ""
    assert body["nonce_required"] is False


@pytest.mark.asyncio
async def test_money_moving_keys_are_flagged_for_nonce_enforcement(client: AsyncClient, db_session):
    minted = await _mint(
        client, identity="kid-signing-e2e-6", perms=["place_order", "sync_task_status"], agent_id="agent-6"
    )
    token = minted.json()["runtime_key"]
    resp = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": token})
    assert resp.status_code == 200
    assert resp.json()["nonce_required"] is True


@pytest.mark.asyncio
async def test_sdk_binds_its_own_key_and_then_signs_every_call(client: AsyncClient, db_session, monkeypatch):
    """SDK 才是 agent 真正用的入口，这条跑通才算「agent 能放心接入」。

    这里把 SDK 自己的 httpx 客户端接到 ASGI app 上，走的是真实 HTTP 语义
    （真发请求、真验签），只是不经过网络。
    """
    import httpx as _httpx
    from httpx import ASGITransport

    import sdk.runtime_client as rt_mod
    from api.app import app as fastapi_app
    from sdk.runtime_client import KarmaRuntime

    class _LocalAsyncClient(_httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs.setdefault("transport", ASGITransport(app=fastapi_app))
            super().__init__(**kwargs)

    monkeypatch.setattr(rt_mod.httpx, "AsyncClient", _LocalAsyncClient)

    minted = await _mint(
        client, identity="kid-sdk-e2e-1", perms=["sync_task_status"], agent_id="agent-sdk-e2e-1"
    )
    assert minted.status_code == 201, minted.text
    monkeypatch.setenv("KARMA_RUNTIME_KEY", minted.json()["runtime_key"])
    monkeypatch.setenv("KARMA_RUNTIME_URL", "http://localhost")
    monkeypatch.setenv("KARMA_AGENT_ID", "agent-sdk-e2e-1")
    monkeypatch.setenv("KARMA_AGENT_PRIVATE_KEY", base64.b64encode(b"\x66" * 32).decode())

    rt = KarmaRuntime.from_env()
    assert rt.has_agent_key() is True
    assert rt.signing_enabled() is False  # 还没确认服务端绑没绑，先不签名

    bound = await rt.ensure_bound()
    assert bound["key_binding"] == "agent"
    assert rt.signing_enabled() is True

    info = await rt.get_permissions()
    assert info["key_binding"] == "agent"
    assert info["agent_fingerprint"] == bound["agent_fingerprint"]
    assert info["key_id"] == minted.json()["key_id"]
