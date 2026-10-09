import base64
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from karma_mcp_server.agent_signing import (
    agent_key_from_seed,
    agent_public_key_b64,
    agent_public_key_fingerprint,
    build_agent_request_message,
    runtime_key_id,
    sign_runtime_request,
)

EXPECTED = (
    "Karma Runtime Request\n"
    "key_id:abc123\n"
    "method:POST\n"
    "path:/runtime/place-order\n"
    "timestamp:2026-10-10T00:00:00Z\n"
    "nonce:deadbeef\n"
    "body_sha256:" + hashlib.sha256(b'{"a":1}').hexdigest()
)


def test_message_format_is_pinned_to_server():
    got = build_agent_request_message(
        key_id="abc123",
        method="post",
        path="/runtime/place-order",
        timestamp="2026-10-10T00:00:00Z",
        nonce="deadbeef",
        body_sha256=hashlib.sha256(b'{"a":1}').hexdigest(),
    )
    assert got == EXPECTED


def test_runtime_key_id():
    assert runtime_key_id("KRM_RT_kid_secret") == "kid"
    assert runtime_key_id("not-a-key") == ""


def test_key_from_hex_and_base64_seed():
    raw = bytes(range(32))
    k1 = agent_key_from_seed(raw.hex())
    k2 = agent_key_from_seed(base64.b64encode(raw).decode())
    assert agent_public_key_b64(k1) == agent_public_key_b64(k2)


def test_bad_seed_raises():
    with pytest.raises(ValueError):
        agent_key_from_seed("short")


def test_sign_headers_and_signature_verifies():
    key = Ed25519PrivateKey.generate()
    headers = sign_runtime_request(
        key=key, key_id="kid", method="POST", path="/runtime/place-order", body=b'{"x":1}'
    )
    assert set(headers) == {
        "X-Karma-Agent-Signature",
        "X-Karma-Runtime-Timestamp",
        "X-Karma-Runtime-Nonce",
    }
    msg = build_agent_request_message(
        key_id="kid",
        method="POST",
        path="/runtime/place-order",
        timestamp=headers["X-Karma-Runtime-Timestamp"],
        nonce=headers["X-Karma-Runtime-Nonce"],
        body_sha256=hashlib.sha256(b'{"x":1}').hexdigest(),
    )
    key.public_key().verify(
        base64.b64decode(headers["X-Karma-Agent-Signature"]), msg.encode("utf-8")
    )


def test_public_key_fingerprint_matches_the_server_formula():
    """主人要在操作台核对的那串：必须等于后端 _public_key_fingerprint 的算法。

    服务端算的是「它收到的那串 base64」的 sha256 前 16 位（services/agent_pairing.py），
    所以这里也按字符串算 —— 差一个编码方式，主人核对的就是两串对不上的数。
    """
    key = Ed25519PrivateKey.generate()
    pub_b64 = agent_public_key_b64(key)
    assert (
        agent_public_key_fingerprint(pub_b64)
        == hashlib.sha256(pub_b64.encode("utf-8")).hexdigest()[:16]
    )
    # 那串就是操作台展示的形态：16 位 hex，不带前缀
    fp = agent_public_key_fingerprint(pub_b64)
    assert len(fp) == 16 and all(c in "0123456789abcdef" for c in fp)
    # 空白容忍（服务端也会 strip 它收到的那串）
    assert agent_public_key_fingerprint("  " + pub_b64 + "  ") == fp
    assert agent_public_key_fingerprint("") == ""


def test_two_different_keys_never_share_a_fingerprint():
    a = agent_public_key_fingerprint(agent_public_key_b64(Ed25519PrivateKey.generate()))
    b = agent_public_key_fingerprint(agent_public_key_b64(Ed25519PrivateKey.generate()))
    assert a != b
