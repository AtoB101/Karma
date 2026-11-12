# -*- coding: utf-8 -*-
"""sign-check 的两件事：结论要准，签出来的原文要跟服务端逐字一致。"""
from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from karma_connect.signcheck import build_probe, verdict


def test_verdict_names_the_actual_break():
    assert "通了" in verdict((401, "sig required"), (200, ""))[0]
    assert "没绑" in verdict((200, ""), (200, ""))[0]
    assert "缺 agent 私钥" in verdict((401, "x"), (401, "X-Karma-Agent-Signature header is required for this runtime key"))[0]
    assert "验不过" in verdict((401, "x"), (401, "agent request signature verification failed"))[0]
    assert "窗口" in verdict((401, "x"), (401, "X-Karma-Runtime-Timestamp is outside the accepted window"))[0]
    assert "nonce" in verdict((401, "x"), (409, "duplicate client_nonce (replay protection)"))[0]
    assert "激活" in verdict((403, "pending"), (403, "key is not active yet"))[0]
    assert "吊销" in verdict((401, "x"), (401, "invalid or revoked runtime key"))[0]


def test_probe_message_matches_the_server_and_verifies():
    from services.runtime_wallet import build_agent_request_message
    from services.signing import signing_service

    key = Ed25519PrivateKey.generate()
    message, headers = build_probe(key_id="k" * 32, method="GET", path="/runtime/permissions")
    expected = build_agent_request_message(
        key_id="k" * 32,
        method="GET",
        path="/runtime/permissions",
        timestamp=headers["X-Karma-Runtime-Timestamp"],
        nonce=headers["X-Karma-Runtime-Nonce"],
        body_sha256=hashlib.sha256(b"").hexdigest(),
    )
    assert message == expected
    assert message.splitlines()[0] == "Karma Runtime Request"

    public = base64.b64encode(
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).decode()
    signature = base64.b64encode(key.sign(message.encode("utf-8"))).decode()
    assert signing_service.verify(message.encode("utf-8"), signature, public) is True
    assert signing_service.verify((message + "x").encode("utf-8"), signature, public) is False


def test_local_fingerprint_is_the_same_count_as_the_console(monkeypatch):
    """本机自检打印的那串指纹，必须和操作台 / 服务端同一口径 —— 否则主人核不对。

    以前这里是 ``"sha256:" + sha256(raw32)[:16]``（对裸字节取哈希、还带前缀），
    操作台显示的是 canonical base64 文本的 sha256 前 16 位，两边永远对不上。
    """
    from karma_connect.signcheck import local_credentials
    from services.runtime_key_service import agent_binding_fingerprint

    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    monkeypatch.setenv("KARMA_AGENT_PRIVATE_KEY", base64.b64encode(seed).decode())
    monkeypatch.setenv("KARMA_AGENT_ID", "agent-test")

    info = local_credentials()
    assert info["agent_public_key_fingerprint"] == agent_binding_fingerprint(
        info["agent_public_key_b64"]
    )
    assert len(info["agent_public_key_fingerprint"]) == 16
    assert ":" not in info["agent_public_key_fingerprint"]
