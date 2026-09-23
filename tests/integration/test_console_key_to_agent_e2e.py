"""
操作台铸钥匙 → agent 申请绑定 → 主人输匹配码 → 钥匙真能用（全链路一条测完）。

这是「用户把钱交给 agent」的最后一公里，所以必须真路由端到端跑一遍，
而不是几支分散的单测拼起来看：

    [1] 操作台侧：钱包 EIP-191 签名 → POST /runtime/create-key（带 agent 绑定）
    [2] agent 侧：POST /runtime/bind-key（带上自己的 Ed25519 公钥）→ 拿到 8 位匹配码
    [3] 没输码之前：花钱的调用一律 403（钥匙「没激活就废」）
    [4] 主人侧：POST /runtime/confirm-bind-key（输码 + 钱包签名）→ 绑定才落库
    [5] 生效之后：带四个头的请求 200；只带 key、不带签名的请求 401

最后两条正是 openclaw 那条路的判据：``karma-openclaw`` 只会发
``X-Karma-Runtime-Key``（见 ``packages/karma-openclaw/karma_openclaw/http_client.py``），
所以它开箱即用的是**托管型 key**（铸 key 时没指定 agent）；绑过 agent 公钥的 key
它签不了名，要靠 ``sdk/runtime_client.py`` 的 ``KarmaRuntime``。
"""
from __future__ import annotations

import base64
import hashlib
import os
import uuid
from datetime import datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient

from services.runtime_wallet import (
    build_agent_request_message,
    build_confirm_bind_message,
    build_create_key_message,
)

PERMISSIONS = ["sync_task_status", "request_voucher", "submit_receipt"]


def _agent_keypair() -> tuple[Ed25519PrivateKey, str]:
    """agent 侧的一对钥匙；公钥按服务端约定编码成 base64(32 字节 raw)。"""
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return key, base64.b64encode(raw).decode()


async def _mint(client: AsyncClient, *, account: Account, identity: str, agent_id: str | None):
    """操作台那一按：钱包签名 + POST /runtime/create-key。"""
    expire = datetime.utcnow() + timedelta(days=30)
    agent_name = f"claw-{identity[-6:]}"
    msg = build_create_key_message(
        karma_identity_id=identity,
        wallet_address=account.address,
        permissions=PERMISSIONS,
        single_limit=100.0,
        daily_limit=500.0,
        expire_time=expire,
        agent_name=agent_name,
        agent_binding=agent_id,
    )
    signed = account.sign_message(encode_defunct(text=msg))
    resp = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": account.address,
            "karma_identity_id": identity,
            "wallet_signature": signed.signature.hex(),
            "permissions": PERMISSIONS,
            "single_limit": 100.0,
            "daily_limit": 500.0,
            "expire_time": expire.isoformat(),
            "agent_name": agent_name,
            "agent_binding": agent_id,
            "agent_id": agent_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _agent_applies(client: AsyncClient, *, token: str, agent_id: str, pubkey: str):
    resp = await client.post(
        "/runtime/bind-key",
        headers={"X-Karma-Runtime-Key": token},
        json={"agent_id": agent_id, "agent_public_key": pubkey, "client_nonce": uuid.uuid4().hex},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _owner_confirms(
    client: AsyncClient, *, account: Account, identity: str, key_id: str, code: str
):
    nonce = uuid.uuid4().hex
    msg = build_confirm_bind_message(
        key_id=key_id,
        karma_identity_id=identity,
        wallet_address=account.address,
        activation_code=code,
        client_nonce=nonce,
    )
    signed = account.sign_message(encode_defunct(text=msg))
    return await client.post(
        "/runtime/confirm-bind-key",
        json={
            "key_id": key_id,
            "karma_identity_id": identity,
            "wallet_address": account.address,
            "wallet_signature": signed.signature.hex(),
            "activation_code": code,
            "client_nonce": nonce,
        },
    )


def _signed_headers(key_id: str, key: Ed25519PrivateKey, *, method: str, path: str, body: bytes):
    """绑过公钥之后每个请求都要带的四个头（agent 自己签）。"""
    import uuid as _uuid

    from datetime import timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = _uuid.uuid4().hex
    message = build_agent_request_message(
        key_id=key_id,
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
    return {
        "X-Karma-Agent-Signature": base64.b64encode(key.sign(message.encode("utf-8"))).decode(),
        "X-Karma-Runtime-Timestamp": timestamp,
        "X-Karma-Runtime-Nonce": nonce,
    }


def _openclaw_runtime_headers(token: str) -> dict:
    """karma-openclaw 真正发出去的那组头 —— 直接调它自己的函数，不靠复述。"""
    from karma_openclaw import http_client as oc

    previous = os.environ.get("KARMA_RUNTIME_KEY")
    os.environ["KARMA_RUNTIME_KEY"] = token
    try:
        return dict(oc.runtime_headers())
    finally:
        if previous is None:
            os.environ.pop("KARMA_RUNTIME_KEY", None)
        else:
            os.environ["KARMA_RUNTIME_KEY"] = previous


@pytest.mark.asyncio
async def test_console_mints_key_agent_binds_owner_confirms_with_code(client: AsyncClient):
    account = Account.create()
    identity = f"e2e-claw-{uuid.uuid4().hex[:10]}"
    agent_id = f"claw-{uuid.uuid4().hex[:8]}"

    # [1] 操作台铸钥匙：指定了 agent，所以钥匙是「待激活」的。
    minted = await _mint(client, account=account, identity=identity, agent_id=agent_id)
    token = str(minted["runtime_key"])
    key_id = str(minted["key_id"])
    assert token.startswith("KRM_RT_")
    assert minted["activation_required"] is True
    assert minted["activation_code_ttl_seconds"] == 180, "匹配码 3 分钟，不是 30 分钟"
    assert "bind-key" in str(minted["next_step"])

    # [2] agent 申请绑定自己的公钥：这一步只拿到匹配码，绑定还没生效。
    agent_key, pubkey = _agent_keypair()
    applied = await _agent_applies(client, token=token, agent_id=agent_id, pubkey=pubkey)
    assert applied["status"] == "pending_activation", applied
    code = str(applied["activation_code"])
    assert len(code.replace("-", "")) == 8
    # 指纹在申请阶段就该给出来（操作台拿它给你肉眼对照），不是等到确认之后。
    assert applied["agent_fingerprint"]
    assert applied["pending_binding"]["agent_fingerprint"] == applied["agent_fingerprint"]
    assert applied["pending_binding"]["attempts_left"] == 5

    # [3] /runtime/permissions 是刻意放行的只读口：agent 靠它回答「我现在到哪一步了」。
    where = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": token})
    assert where.status_code == 200, where.text
    assert where.json()["key_binding"] == "agent_pending"
    assert where.json()["activation_required"] is True
    assert where.json()["agent_fingerprint"], "未激活时也该给出指纹，操作台靠它对照"

    # 除它以外一律 403：没激活的钥匙动不了钱，也没有时间宽限。
    blocked = await client.get("/runtime/capacity", headers={"X-Karma-Runtime-Key": token})
    assert blocked.status_code == 403, blocked.text
    assert "not activated" in str(blocked.json().get("detail"))

    # [4] 重新申请会发新码、把旧码作废 —— 码不是「有效期内随便用」的长期凭证。
    #     （agent 重启后再申请一次就会走到这里：主人手上那张旧码随之失效。）
    again = await _agent_applies(client, token=token, agent_id=agent_id, pubkey=pubkey)
    assert again["status"] == "pending_activation"
    fresh = str(again["activation_code"])
    assert fresh != code
    assert again["pending_binding"]["attempts_left"] == 5

    stale = await _owner_confirms(
        client, account=account, identity=identity, key_id=key_id, code=code
    )
    assert stale.status_code == 403, stale.text
    assert "does not match" in str(stale.json().get("detail"))

    # [5] 主人拿**当前那张**码 + 钱包签名 → 绑定才落库。
    confirmed = await _owner_confirms(
        client, account=account, identity=identity, key_id=key_id, code=fresh
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "active"
    assert confirmed.json()["agent_id"] == agent_id

    # [6] 生效之后：带四个头 200；只带 key 401。
    headers = _signed_headers(key_id, agent_key, method="GET", path="/runtime/permissions", body=b"")
    headers["X-Karma-Runtime-Key"] = token
    ok = await client.get("/runtime/permissions", headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["key_binding"] == "agent"

    unsigned = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": token})
    assert unsigned.status_code == 401, unsigned.text

    # openclaw 发的那组头就等于「只带 key」—— 所以它在绑定型钥匙上必然被拒。
    oc_headers = _openclaw_runtime_headers(token)
    assert "X-Karma-Agent-Signature" not in oc_headers
    oc_call = await client.get("/runtime/permissions", headers=oc_headers)
    assert oc_call.status_code == 401, oc_call.text


@pytest.mark.asyncio
async def test_wrong_matching_code_is_rejected_and_does_not_activate(client: AsyncClient):
    account = Account.create()
    identity = f"e2e-claw-bad-{uuid.uuid4().hex[:8]}"
    agent_id = f"claw-{uuid.uuid4().hex[:8]}"

    minted = await _mint(client, account=account, identity=identity, agent_id=agent_id)
    token, key_id = str(minted["runtime_key"]), str(minted["key_id"])
    _agent_key, pubkey = _agent_keypair()
    await _agent_applies(client, token=token, agent_id=agent_id, pubkey=pubkey)

    # 别人偷到钥匙、但没有那串码：胡乱敲一个，绑定不能生效。
    wrong = await _owner_confirms(
        client, account=account, identity=identity, key_id=key_id, code="AAAA-AAAA"
    )
    assert wrong.status_code in (400, 401, 403, 422), wrong.text

    still = await client.get("/runtime/capacity", headers={"X-Karma-Runtime-Key": token})
    assert still.status_code == 403, still.text


@pytest.mark.asyncio
async def test_service_mode_key_is_usable_by_openclaw_out_of_the_box(client: AsyncClient):
    """操作台不指定 agent 时铸的是「托管型」钥匙：光有 key 就能用 —— openclaw 走的正是这条。"""
    account = Account.create()
    identity = f"e2e-claw-svc-{uuid.uuid4().hex[:8]}"

    minted = await _mint(client, account=account, identity=identity, agent_id=None)
    token = str(minted["runtime_key"])
    assert minted["activation_required"] is False
    assert "托管" in str(minted["next_step"])

    headers = _openclaw_runtime_headers(token)
    assert headers.get("X-Karma-Runtime-Key") == token

    resp = await client.get("/runtime/capacity", headers=headers)
    assert resp.status_code == 200, resp.text
