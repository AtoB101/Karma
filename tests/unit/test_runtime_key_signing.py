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
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient

from services import runtime_key_service as rks
from services.runtime_wallet import (
    build_agent_request_message,
    build_confirm_bind_message,
    build_create_key_message,
    build_list_bind_requests_message,
    build_list_keys_message,
    build_reject_bind_message,
)
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

async def _mint_full(
    client: AsyncClient, *, identity: str, perms: list[str], agent_id: str, **kw
):
    """铸一把 Runtime Key，并把铸它的钱包一起交出来（确认绑定要用同一个钱包签名）。"""
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
    resp = await client.post("/runtime/create-key", json=body)
    return resp, acct


async def _mint(client: AsyncClient, *, identity: str, perms: list[str], agent_id: str, **kw):
    resp, _ = await _mint_full(client, identity=identity, perms=perms, agent_id=agent_id, **kw)
    return resp


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
    """两阶段绑定：agent 申请拿码 → 主人输码签名 → 之后每个请求都要验签。"""
    identity = "kid-signing-e2e-1"
    agent_id = "agent-signing-e2e-1"
    minted, wallet = await _mint_full(
        client, identity=identity, perms=["sync_task_status"], agent_id=agent_id
    )
    assert minted.status_code == 201, minted.text
    data = minted.json()
    token = data["runtime_key"]
    key_id = data["key_id"]
    assert data["key_binding"] == "service"  # 铸造时还没绑公钥
    assert data["binding_scope"].startswith("Karma Runtime Key Binding")
    assert data["binding_scope_signature"]

    # 绑定前：老路径，不带签名也能读
    pre = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": token})
    assert pre.status_code == 200
    assert pre.json()["key_binding"] == "service"

    agent_key = agent_key_from_seed(base64.b64encode(b"\x44" * 32).decode())
    pub = _pub_of(agent_key)

    # 第一步：申请。拿到码，但绑定还没生效。
    requested = await _request_bind(client, token, agent_id, pub)
    assert requested.status_code == 200, requested.text
    payload = requested.json()
    assert payload["status"] == "pending_activation"
    assert payload["key_binding"] == "service"
    code = payload["activation_code"]
    assert re.fullmatch(r"[0-9A-Z]{4}-[0-9A-Z]{4}", code)
    assert payload["activation_code_hint"]
    assert payload["pending_binding"]["agent_fingerprint"]

    # 还没确认：老路径照旧能读；这时候带签名反而 403（服务端不认这把公钥）
    during = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": token})
    assert during.status_code == 200
    assert during.json()["key_binding"] == "service"
    early = await client.get(
        "/runtime/permissions",
        headers=_headers_for(token, agent_key, method="GET", path="/runtime/permissions", body=b""),
    )
    assert early.status_code == 403

    # 码错 → 403
    bad = await client.post(
        "/runtime/confirm-bind-key",
        json=_confirm_body(key_id=key_id, identity=identity, acct=wallet, code=_wrong_code(code)),
    )
    assert bad.status_code == 403, bad.text

    # 第二步：主人输码 + 钱包签名 → 绑定才真正落库
    confirmed = await client.post(
        "/runtime/confirm-bind-key",
        json=_confirm_body(key_id=key_id, identity=identity, acct=wallet, code=code),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["key_binding"] == "agent"
    assert confirmed.json()["binding_scope_signature"]

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
    assert signed.json()["pending_binding"] is None

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

    minted, wallet = await _mint_full(
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

    # 申请只是拿到匹配码：这时候开签名只会吃 403，SDK 不该自作主张。
    pending = await rt.ensure_bound()
    assert pending["status"] == "pending_activation"
    assert pending["activation_code"]
    assert rt.signing_enabled() is False
    assert rt.pending_activation is not None

    # 主人还没输码：agent 走老路径照样能读
    waiting = await rt.get_permissions()
    assert waiting["key_binding"] == "service"

    # 主人拿 agent 给的码在操作台签名确认
    confirmed = await client.post(
        "/runtime/confirm-bind-key",
        json=_confirm_body(
            key_id=minted.json()["key_id"],
            identity="kid-sdk-e2e-1",
            acct=wallet,
            code=pending["activation_code"],
        ),
    )
    assert confirmed.status_code == 200, confirmed.text

    bound = await rt.await_binding_activation(timeout_seconds=5, interval_seconds=0.1)
    assert rt.signing_enabled() is True
    assert rt.pending_activation is None
    assert bound["key_binding"] == "agent"

    info = await rt.get_permissions()
    assert info["key_binding"] == "agent"
    assert info["agent_fingerprint"] == confirmed.json()["agent_fingerprint"]
    assert info["key_id"] == minted.json()["key_id"]
# ---------------------------------------------------------------- 匹配码激活

def _pub_of(key) -> str:
    from cryptography.hazmat.primitives import serialization

    return base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()


def _wrong_code(code: str) -> str:
    """一个格式合法、但一定不是这把 key 的码。"""
    body = code.replace("-", "")
    return body[:-1] + ("2" if body[-1] != "2" else "3")


def _confirm_body(*, key_id: str, identity: str, acct, code: str, nonce: str | None = None):
    nonce = nonce or uuid.uuid4().hex
    msg = build_confirm_bind_message(
        key_id=key_id,
        karma_identity_id=identity,
        wallet_address=acct.address,
        activation_code=code,
        client_nonce=nonce,
    )
    return {
        "key_id": key_id,
        "karma_identity_id": identity,
        "wallet_address": acct.address,
        "wallet_signature": acct.sign_message(encode_defunct(text=msg)).signature.hex(),
        "activation_code": code,
        "client_nonce": nonce,
    }


def _reject_body(*, key_id: str, identity: str, acct, nonce: str | None = None):
    nonce = nonce or uuid.uuid4().hex
    msg = build_reject_bind_message(
        key_id=key_id,
        karma_identity_id=identity,
        wallet_address=acct.address,
        client_nonce=nonce,
    )
    return {
        "key_id": key_id,
        "karma_identity_id": identity,
        "wallet_address": acct.address,
        "wallet_signature": acct.sign_message(encode_defunct(text=msg)).signature.hex(),
        "client_nonce": nonce,
    }


async def _request_bind(client: AsyncClient, token: str, agent_id: str, pub: str, key=None, **kw):
    payload = {
        "agent_id": agent_id,
        "agent_public_key": pub,
        "client_nonce": kw.pop("nonce", uuid.uuid4().hex),
    }
    body = json.dumps(payload).encode()
    if key is None:
        headers = {"X-Karma-Runtime-Key": token, "Content-Type": "application/json"}
    else:
        headers = _headers_for(
            token, key, method="POST", path="/runtime/bind-key", body=body, **kw
        )
    return await client.post("/runtime/bind-key", content=body, headers=headers)


@pytest.mark.asyncio
async def test_wrong_activation_code_burns_attempts_and_then_the_request(
    client: AsyncClient, db_session
):
    """码错了要计数：试满 5 次这条请求作废，得让 agent 重新申请。"""
    minted, wallet = await _mint_full(
        client, identity="kid-code-1", perms=["sync_task_status"], agent_id="agent-code-1"
    )
    data = minted.json()
    token, key_id = data["runtime_key"], data["key_id"]
    agent_key = agent_key_from_seed(base64.b64encode(b"\x71" * 32).decode())

    requested = await _request_bind(client, token, "agent-code-1", _pub_of(agent_key))
    assert requested.status_code == 200, requested.text
    payload = requested.json()
    assert payload["status"] == "pending_activation"
    assert payload["key_binding"] == "service"  # 申请了，但还没生效
    code = payload["activation_code"]
    assert re.fullmatch(r"[0-9A-Z]{4}-[0-9A-Z]{4}", code)
    assert (payload["pending_binding"] or {}).get("agent_fingerprint")
    assert payload["activation_attempts_left"] == 5

    for _ in range(5):
        bad = await client.post(
            "/runtime/confirm-bind-key",
            json=_confirm_body(key_id=key_id, identity="kid-code-1", acct=wallet, code=_wrong_code(code)),
        )
        assert bad.status_code == 403, bad.text

    # 第 6 次：试错额度用完，待确认请求直接作废
    over = await client.post(
        "/runtime/confirm-bind-key",
        json=_confirm_body(key_id=key_id, identity="kid-code-1", acct=wallet, code=_wrong_code(code)),
    )
    assert over.status_code == 429, over.text

    # 作废之后连正确的码也没用了
    late = await client.post(
        "/runtime/confirm-bind-key",
        json=_confirm_body(key_id=key_id, identity="kid-code-1", acct=wallet, code=code),
    )
    assert late.status_code == 409, late.text


@pytest.mark.asyncio
async def test_expired_activation_code_clears_the_request(client: AsyncClient, db_session):
    from db.models.orm import RuntimeKeyModel

    minted, wallet = await _mint_full(
        client, identity="kid-code-2", perms=["sync_task_status"], agent_id="agent-code-2"
    )
    data = minted.json()
    token, key_id = data["runtime_key"], data["key_id"]
    agent_key = agent_key_from_seed(base64.b64encode(b"\x72" * 32).decode())
    requested = await _request_bind(client, token, "agent-code-2", _pub_of(agent_key))
    code = requested.json()["activation_code"]

    row = await db_session.get(RuntimeKeyModel, key_id)
    row.pending_expires_at = datetime.utcnow() - timedelta(minutes=1)
    await db_session.commit()

    resp = await client.post(
        "/runtime/confirm-bind-key",
        json=_confirm_body(key_id=key_id, identity="kid-code-2", acct=wallet, code=code),
    )
    assert resp.status_code == 410, resp.text
    assert "new one" in resp.json()["detail"]

    again = await client.post(
        "/runtime/confirm-bind-key",
        json=_confirm_body(key_id=key_id, identity="kid-code-2", acct=wallet, code=code),
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_confirm_bind_needs_the_owners_wallet_and_the_right_identity(
    client: AsyncClient, db_session
):
    minted, wallet = await _mint_full(
        client, identity="kid-code-3", perms=["sync_task_status"], agent_id="agent-code-3"
    )
    data = minted.json()
    token, key_id = data["runtime_key"], data["key_id"]
    agent_key = agent_key_from_seed(base64.b64encode(b"\x73" * 32).decode())
    requested = await _request_bind(client, token, "agent-code-3", _pub_of(agent_key))
    code = requested.json()["activation_code"]

    # 别人的钱包签的码不作数
    stranger = Account.create()
    stolen = await client.post(
        "/runtime/confirm-bind-key",
        json=_confirm_body(key_id=key_id, identity="kid-code-3", acct=stranger, code=code),
    )
    assert stolen.status_code == 403, stolen.text

    # key 不属于这个身份 → 404
    wrong_identity = _confirm_body(key_id=key_id, identity="kid-code-3", acct=wallet, code=code)
    wrong_identity["karma_identity_id"] = "kid-someone-else"
    foreign = await client.post("/runtime/confirm-bind-key", json=wrong_identity)
    assert foreign.status_code == 404

    # 谁都没确认过，绑定不该生效
    info = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": token})
    assert info.status_code == 200
    assert info.json()["key_binding"] == "service"


@pytest.mark.asyncio
async def test_reject_clears_the_request_and_the_agent_can_ask_again(
    client: AsyncClient, db_session
):
    minted, wallet = await _mint_full(
        client, identity="kid-code-4", perms=["sync_task_status"], agent_id="agent-code-4"
    )
    data = minted.json()
    token, key_id = data["runtime_key"], data["key_id"]
    agent_key = agent_key_from_seed(base64.b64encode(b"\x74" * 32).decode())
    pub = _pub_of(agent_key)
    requested = await _request_bind(client, token, "agent-code-4", pub)
    code = requested.json()["activation_code"]

    rejected = await client.post(
        "/runtime/reject-bind-key",
        json=_reject_body(key_id=key_id, identity="kid-code-4", acct=wallet),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["pending_binding"] is None

    # 拒了之后旧码立刻失效
    dead = await client.post(
        "/runtime/confirm-bind-key",
        json=_confirm_body(key_id=key_id, identity="kid-code-4", acct=wallet, code=code),
    )
    assert dead.status_code == 409

    # agent 重新申请 → 新码，且旧码不会被复用
    again = await _request_bind(client, token, "agent-code-4", pub)
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "pending_activation"
    assert again.json()["activation_code"] != code

    # 没有待确认请求时再点拒绝 → 409
    await client.post(
        "/runtime/reject-bind-key",
        json=_reject_body(key_id=key_id, identity="kid-code-4", acct=wallet),
    )
    empty = await client.post(
        "/runtime/reject-bind-key",
        json=_reject_body(key_id=key_id, identity="kid-code-4", acct=wallet),
    )
    assert empty.status_code == 409


@pytest.mark.asyncio
async def test_confirm_then_rebind_from_the_same_key_is_idempotent(
    client: AsyncClient, db_session
):
    minted, wallet = await _mint_full(
        client, identity="kid-code-5", perms=["sync_task_status"], agent_id="agent-code-5"
    )
    data = minted.json()
    token, key_id = data["runtime_key"], data["key_id"]
    agent_key = agent_key_from_seed(base64.b64encode(b"\x75" * 32).decode())
    pub = _pub_of(agent_key)
    requested = await _request_bind(client, token, "agent-code-5", pub)
    code = requested.json()["activation_code"]

    confirmed = await client.post(
        "/runtime/confirm-bind-key",
        json=_confirm_body(key_id=key_id, identity="kid-code-5", acct=wallet, code=code),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["key_binding"] == "agent"
    assert confirmed.json()["binding_scope"].startswith("Karma Runtime Key Binding")
    assert confirmed.json()["binding_scope_signature"]
    assert confirmed.json()["pending_binding"] is None

    # agent 重启后再申请一次：同一把公钥 → 幂等，不发新码
    again = await _request_bind(client, token, "agent-code-5", pub, key=agent_key)
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["status"] == "active"
    assert "activation_code" not in body
    assert body["key_binding"] == "agent"
    assert body["binding_scope_signature"]

    # 换一把公钥 → 409，告诉用户先吊销再铸新的
    other = agent_key_from_seed(base64.b64encode(b"\x76" * 32).decode())
    swap = await _request_bind(client, token, "agent-code-5", _pub_of(other), key=agent_key)
    assert swap.status_code == 409


@pytest.mark.asyncio
async def test_console_can_list_pending_bind_requests_and_see_them_on_keys(
    client: AsyncClient, db_session
):
    minted, wallet = await _mint_full(
        client, identity="kid-code-6", perms=["sync_task_status"], agent_id="agent-code-6"
    )
    data = minted.json()
    token, key_id = data["runtime_key"], data["key_id"]
    agent_key = agent_key_from_seed(base64.b64encode(b"\x77" * 32).decode())
    requested = await _request_bind(client, token, "agent-code-6", _pub_of(agent_key))
    fingerprint = requested.json()["pending_binding"]["agent_fingerprint"]

    # list-keys 上带着待确认请求
    nonce = uuid.uuid4().hex
    msg = build_list_keys_message(
        karma_identity_id="kid-code-6", wallet_address=wallet.address, client_nonce=nonce
    )
    keys = await client.post(
        "/runtime/list-keys",
        json={
            "karma_identity_id": "kid-code-6",
            "wallet_address": wallet.address,
            "wallet_signature": wallet.sign_message(encode_defunct(text=msg)).signature.hex(),
            "client_nonce": nonce,
        },
    )
    assert keys.status_code == 200, keys.text
    row = [k for k in keys.json()["keys"] if k["key_id"] == key_id][0]
    assert row["pending_binding"]["agent_fingerprint"] == fingerprint

    # list-bind-requests 只认领签名那个钱包的 key
    nonce2 = uuid.uuid4().hex
    msg2 = build_list_bind_requests_message(
        karma_identity_id="kid-code-6", wallet_address=wallet.address, client_nonce=nonce2
    )
    listed = await client.post(
        "/runtime/list-bind-requests",
        json={
            "karma_identity_id": "kid-code-6",
            "wallet_address": wallet.address,
            "wallet_signature": wallet.sign_message(encode_defunct(text=msg2)).signature.hex(),
            "client_nonce": nonce2,
        },
    )
    assert listed.status_code == 200, listed.text
    requests = listed.json()["requests"]
    assert [r["key_id"] for r in requests] == [key_id]
    assert requests[0]["agent_fingerprint"] == fingerprint
    assert requests[0]["agent_name"] == "signing-test"

    # 另一个钱包签名 → 请求本身合法，但看不到别人的 key
    stranger = Account.create()
    nonce3 = uuid.uuid4().hex
    msg3 = build_list_bind_requests_message(
        karma_identity_id="kid-code-6", wallet_address=stranger.address, client_nonce=nonce3
    )
    foreign = await client.post(
        "/runtime/list-bind-requests",
        json={
            "karma_identity_id": "kid-code-6",
            "wallet_address": stranger.address,
            "wallet_signature": stranger.sign_message(encode_defunct(text=msg3)).signature.hex(),
            "client_nonce": nonce3,
        },
    )
    assert foreign.status_code == 200
    assert foreign.json()["requests"] == []

    # 而 agent 侧看 permissions 时也带着这条待确认请求
    info = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": token})
    assert info.status_code == 200
    assert info.json()["pending_binding"]["agent_fingerprint"] == fingerprint


@pytest.mark.asyncio
async def test_console_polls_pending_binds_with_session_auth_only(client: AsyncClient, db_session):
    """进页面就能看见「有 agent 在申请接入」：这条只认会话身份，不打钱包签名弹窗。

    分工：``/runtime/list-bind-requests`` 要钱包签名（身份不可辩驳，用户主动发起）；
    ``/runtime/list-pending-binds`` 只认会话（SIWE / X-Karma-Identity-Id），
    好让操作台一进页面就提示 —— 看一眼提示不该惊动钱包。
    """
    mine, wallet = await _mint_full(
        client, identity="kid-code-7", perms=["sync_task_status"], agent_id="agent-code-7"
    )
    token, key_id = mine.json()["runtime_key"], mine.json()["key_id"]
    agent_key = agent_key_from_seed(base64.b64encode(b"\x78" * 32).decode())
    requested = await _request_bind(client, token, "agent-code-7", _pub_of(agent_key))
    fingerprint = requested.json()["pending_binding"]["agent_fingerprint"]

    # ① 没身份：403，而且路由是存在的（不是 404）
    anon = await client.post("/runtime/list-pending-binds", json={"karma_identity_id": "kid-code-7"})
    assert anon.status_code == 403, anon.text

    # ② 会话身份与 body 里写的身份不一致 → 403：别想拿别人的身份名问出待确认请求
    mismatch = await client.post(
        "/runtime/list-pending-binds",
        json={"karma_identity_id": "kid-someone-else"},
        headers={"X-Karma-Identity-Id": "kid-code-7"},
    )
    assert mismatch.status_code == 403, mismatch.text

    # ③ 自己的身份：只回自己名下那把 key，且不带匹配码明文（服务端只存 HMAC）
    listed = await client.post(
        "/runtime/list-pending-binds",
        json={"karma_identity_id": "kid-code-7"},
        headers={"X-Karma-Identity-Id": "kid-code-7"},
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["requests"]
    assert [r["key_id"] for r in rows] == [key_id]
    assert rows[0]["agent_fingerprint"] == fingerprint
    assert rows[0]["agent_name"] == "signing-test"
    assert "activation_code" not in rows[0]
    assert "pending_code_hash" not in rows[0]

    # ④ 身份留空 = 用会话身份（操作台在还没拿到 identity 时也问得出来）
    blank = await client.post(
        "/runtime/list-pending-binds",
        json={"karma_identity_id": ""},
        headers={"X-Karma-Identity-Id": "kid-code-7"},
    )
    assert blank.status_code == 200, blank.text
    assert [r["key_id"] for r in blank.json()["requests"]] == [key_id]

    # ⑤ 另一张身份卡看不到这条请求
    theirs, _their_wallet = await _mint_full(
        client, identity="kid-code-8", perms=["sync_task_status"], agent_id="agent-code-8"
    )
    their_token = theirs.json()["runtime_key"]
    their_key = agent_key_from_seed(base64.b64encode(b"\x79" * 32).decode())
    await _request_bind(client, their_token, "agent-code-8", _pub_of(their_key))

    other = await client.post(
        "/runtime/list-pending-binds",
        json={"karma_identity_id": "kid-code-8"},
        headers={"X-Karma-Identity-Id": "kid-code-8"},
    )
    assert other.status_code == 200, other.text
    theirs_ids = [r["key_id"] for r in other.json()["requests"]]
    assert theirs_ids == [theirs.json()["key_id"]]
    assert key_id not in theirs_ids

    # ⑥ 主人确认之后，这条请求从列表里消失
    confirmed = await client.post(
        "/runtime/confirm-bind-key",
        json=_confirm_body(
            key_id=key_id,
            identity="kid-code-7",
            acct=wallet,
            code=requested.json()["activation_code"],
        ),
    )
    assert confirmed.status_code == 200, confirmed.text
    after = await client.post(
        "/runtime/list-pending-binds",
        json={"karma_identity_id": "kid-code-7"},
        headers={"X-Karma-Identity-Id": "kid-code-7"},
    )
    assert after.json()["requests"] == []
