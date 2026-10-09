"""主人签名里钉下的 agent 公钥指纹：绑定那一刻必须对得上。

铸造 Runtime Key 时主人签的那段文字里有 ``agent_public_key_fingerprint``。它把
「这把钱钥匙授权给哪把 agent 公钥」写进了主人本人的签名里 —— 不再是一个可以随手
改写的名字（``agent_binding``）。绑定那一刻服务端拿 agent 交上来的真实公钥重算
指纹，对不上直接拒绝。

两个方向都要钉死：
* 指纹进得了签名、也出不了签名（改一个字节就 403）；
* 指纹不对，绑定就不能落地 —— 三条绑定路径（直接激活 / 匹配码申请 / 输码确认）都算。
"""
from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException
from httpx import AsyncClient

from services.runtime_key_service import (
    activate_key_binding,
    agent_binding_fingerprint,
    create_runtime_key_record,
    normalize_agent_key_fingerprint_claim,
    request_key_binding,
)
from services.runtime_wallet import build_create_key_message

IDENTITY = "kid-signed-fingerprint-01"
WALLET = "0x" + "5a" * 20


def _agent_key() -> tuple[object, str, str]:
    """返回 (私钥, 公钥 base64, 公钥指纹) —— 指纹按全系统唯一口径算。"""
    key = Ed25519PrivateKey.generate()
    pub = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    return key, pub, agent_binding_fingerprint(pub)


async def _mint(db_session, *, fingerprint: str | None, agent_binding: str | None = "agent-1"):
    token, row = await create_runtime_key_record(
        db=db_session,
        wallet_address=WALLET,
        karma_identity_id=IDENTITY,
        permissions=["request_voucher"],
        single_limit=10.0,
        daily_limit=20.0,
        expire_at=None,
        agent_name="claw-1",
        agent_binding=agent_binding,
        agent_public_key_fingerprint=fingerprint,
    )
    return token, row


# --------------------------------------------------------------------------
# 指纹在签名里：改了就对不上
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_key_rejects_a_fingerprint_that_was_not_signed(client: AsyncClient):
    """指纹是签名覆盖的字段：签名之后再塞一个进去，必须 403。"""
    acct = Account.create()
    perms = ["request_voucher"]
    signed_without = build_create_key_message(
        karma_identity_id=IDENTITY,
        wallet_address=acct.address,
        permissions=perms,
        single_limit=10.0,
        daily_limit=20.0,
        expire_time=None,
        agent_name="claw-1",
        agent_binding="agent-1",
    )
    sig = acct.sign_message(encode_defunct(text=signed_without)).signature.hex()
    resp = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": acct.address,
            "karma_identity_id": IDENTITY,
            "wallet_signature": sig,
            "permissions": perms,
            "single_limit": 10.0,
            "daily_limit": 20.0,
            "agent_name": "claw-1",
            "agent_binding": "agent-1",
            # 事后加上去的指纹：签名里没有它 → 恢复出来的签名人对不上。
            "agent_public_key_fingerprint": "a1b2c3d4e5f60718",
        },
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_create_key_accepts_the_fingerprint_when_it_is_signed(client: AsyncClient):
    acct = Account.create()
    perms = ["request_voucher"]
    fingerprint = "a1b2c3d4e5f60718"
    msg = build_create_key_message(
        karma_identity_id=IDENTITY,
        wallet_address=acct.address,
        permissions=perms,
        single_limit=10.0,
        daily_limit=20.0,
        expire_time=None,
        agent_name="claw-1",
        agent_binding="agent-1",
        agent_public_key_fingerprint=fingerprint,
    )
    sig = acct.sign_message(encode_defunct(text=msg)).signature.hex()
    resp = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": acct.address,
            "karma_identity_id": IDENTITY,
            "wallet_signature": sig,
            "permissions": perms,
            "single_limit": 10.0,
            "daily_limit": 20.0,
            "agent_name": "claw-1",
            "agent_binding": "agent-1",
            "agent_public_key_fingerprint": fingerprint,
        },
    )
    assert resp.status_code == 201, resp.text


# --------------------------------------------------------------------------
# 指纹约束绑定：三条路径都要拦
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activation_refuses_a_different_agent_key(db_session):
    _key, pub, fp = _agent_key()
    _other_key, other_pub, _other_fp = _agent_key()
    _token, row = await _mint(db_session, fingerprint=fp)

    with pytest.raises(HTTPException) as err:
        await activate_key_binding(
            db=db_session, key_id=row.key_id, agent_id="agent-1", agent_public_key=other_pub
        )
    assert err.value.status_code == 403

    # 换成主人签过的那把公钥就放行。
    bound = await activate_key_binding(
        db=db_session, key_id=row.key_id, agent_id="agent-1", agent_public_key=pub
    )
    assert bound.key_binding == "agent"
    assert bound.agent_public_key == pub


@pytest.mark.asyncio
async def test_matching_code_path_refuses_a_different_agent_key(db_session):
    """申请匹配码这条路也不能绕过指纹：码都不该发出去。"""
    _key, pub, fp = _agent_key()
    _other_key, other_pub, _other_fp = _agent_key()
    _token, row = await _mint(db_session, fingerprint=fp)

    with pytest.raises(HTTPException) as err:
        await request_key_binding(
            db=db_session, key_id=row.key_id, agent_id="agent-1", agent_public_key=other_pub
        )
    assert err.value.status_code == 403

    _row, code, status = await request_key_binding(
        db=db_session, key_id=row.key_id, agent_id="agent-1", agent_public_key=pub
    )
    assert status == "pending_activation"
    assert code


@pytest.mark.asyncio
async def test_legacy_key_without_a_signed_fingerprint_still_binds(db_session):
    """老钥匙（没签过指纹）行为不变：绑定任意 agent 公钥都能过。"""
    _key, pub, _fp = _agent_key()
    _token, row = await _mint(db_session, fingerprint=None)
    bound = await activate_key_binding(
        db=db_session, key_id=row.key_id, agent_id="agent-1", agent_public_key=pub
    )
    assert row.agent_public_key_fingerprint is None
    assert bound.agent_public_key == pub


# --------------------------------------------------------------------------
# 指纹本身必须是 16 位 hex
# --------------------------------------------------------------------------


def test_fingerprint_claim_must_be_16_hex_chars():
    assert normalize_agent_key_fingerprint_claim(None) is None
    assert normalize_agent_key_fingerprint_claim("  ") is None
    assert normalize_agent_key_fingerprint_claim("A1B2C3D4E5F60718") == "a1b2c3d4e5f60718"
    for bad in ("a1b2c3", "z" * 16, "a1b2c3d4e5f607181"):
        with pytest.raises(HTTPException) as err:
            normalize_agent_key_fingerprint_claim(bad)
        assert err.value.status_code == 400


@pytest.mark.asyncio
async def test_a_malformed_fingerprint_never_reaches_the_database(db_session):
    _key, _pub, _fp = _agent_key()
    with pytest.raises(HTTPException) as err:
        await _mint(db_session, fingerprint="not-a-fingerprint")
    assert err.value.status_code == 400


def test_fingerprint_is_stable_across_base64_and_hex_spellings():
    """同一把公钥的两种写法必须落到同一串指纹，否则主人核对的就是两个值。"""
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    b64 = base64.b64encode(raw).decode()
    assert agent_binding_fingerprint(b64) == agent_binding_fingerprint(raw.hex())
    assert agent_binding_fingerprint("0x" + raw.hex()) == agent_binding_fingerprint(b64)
    # 口径钉死：canonical base64 文本的 sha256 前 16 位。
    assert agent_binding_fingerprint(b64) == hashlib.sha256(b64.encode()).hexdigest()[:16]
