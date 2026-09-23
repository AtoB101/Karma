"""OpenClaw 包自带的签名语义（不依赖仓库服务端代码）。

这个包是分发给 agent 运行时的，所以这里的用例只用标准库 + cryptography：
签名消息怎么排、公钥怎么编码、什么时候**不能**带签名。
"""

import base64
import hashlib

import pytest

from karma_openclaw import http_client
from karma_openclaw.agent_binding import (
    agent_key_from_seed,
    agent_public_key_b64,
    build_agent_request_message,
    runtime_key_id,
    sign_runtime_request,
)

KEY_ID = "a" * 32
TOKEN = "KRM_RT_" + KEY_ID + "_" + "b" * 64
SEED = base64.b64encode(bytes(range(32))).decode()


def _key():
    return agent_key_from_seed(SEED)


def _ed25519_public():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    return Ed25519PublicKey.from_public_bytes(base64.b64decode(agent_public_key_b64(_key())))


def test_runtime_key_id_reads_the_middle_segment():
    assert runtime_key_id(TOKEN) == KEY_ID
    assert runtime_key_id("KRM_RT_" + KEY_ID) == KEY_ID
    assert runtime_key_id("not-a-key") == ""


def test_seed_accepts_base64_and_hex():
    assert agent_public_key_b64(agent_key_from_seed(SEED)) == agent_public_key_b64(_key())
    hex_seed = bytes(range(32)).hex()
    assert agent_public_key_b64(agent_key_from_seed(hex_seed)) == agent_public_key_b64(_key())
    with pytest.raises(ValueError):
        agent_key_from_seed("not-base64-not-hex-not-32-bytes")


def test_public_key_is_32_raw_bytes_in_base64():
    assert len(base64.b64decode(agent_public_key_b64(_key()))) == 32


def test_message_is_line_by_line_pinned():
    message = build_agent_request_message(
        key_id=KEY_ID,
        method="post",
        path="/runtime/place-order",
        timestamp="2026-09-18T12:00:00Z",
        nonce="n" * 16,
        body_sha256=hashlib.sha256(b"{}").hexdigest(),
    )
    lines = message.split("\n")
    assert lines[0] == "Karma Runtime Request"
    assert lines[1] == "key_id:" + KEY_ID
    assert lines[2] == "method:POST"  # 方法一律大写
    assert lines[3] == "path:/runtime/place-order"
    assert lines[4] == "timestamp:2026-09-18T12:00:00Z"
    assert lines[5] == "nonce:" + "n" * 16
    assert lines[6] == "body_sha256:" + hashlib.sha256(b"{}").hexdigest()


def test_signature_covers_the_exact_body():
    key = _key()
    body = b'{"a":1}'
    headers = sign_runtime_request(
        key=key, key_id=KEY_ID, method="POST", path="/runtime/submit-receipt", body=body
    )
    assert set(headers) == {
        "X-Karma-Agent-Signature",
        "X-Karma-Runtime-Timestamp",
        "X-Karma-Runtime-Nonce",
    }
    message = build_agent_request_message(
        key_id=KEY_ID,
        method="POST",
        path="/runtime/submit-receipt",
        timestamp=headers["X-Karma-Runtime-Timestamp"],
        nonce=headers["X-Karma-Runtime-Nonce"],
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
    _ed25519_public().verify(
        base64.b64decode(headers["X-Karma-Agent-Signature"]), message.encode("utf-8")
    )


def test_headers_stay_plain_until_the_binding_is_confirmed(monkeypatch):
    """服务端对未绑定的 key 带签名是 403：开关默认必须是关的。"""
    monkeypatch.setenv("KARMA_RUNTIME_KEY", TOKEN)
    monkeypatch.setenv("KARMA_AGENT_PRIVATE_KEY", SEED)
    http_client.reset_signing_mode()
    try:
        plain = http_client.runtime_headers(method="GET", path="/runtime/permissions")
        assert "X-Karma-Agent-Signature" not in plain
        assert plain["X-Karma-Runtime-Key"] == TOKEN

        http_client._set_signing_mode(True)
        signed = http_client.runtime_headers(method="GET", path="/runtime/permissions")
        assert signed["X-Karma-Agent-Signature"]
        assert signed["X-Karma-Runtime-Nonce"]
    finally:
        http_client.reset_signing_mode()


def test_no_runtime_key_is_an_error_not_a_bearer_request(monkeypatch):
    monkeypatch.delenv("KARMA_RUNTIME_KEY", raising=False)
    with pytest.raises(RuntimeError):
        http_client.runtime_headers()


def test_runtime_json_body_is_the_signed_bytes():
    body = http_client.runtime_json_body({"a": 1, "b": "中文"})
    assert body.decode("utf-8") == '{"a":1,"b":"中文"}'
    assert b"\xe4" in body  # 真字节，不是转义文本

def test_the_real_mcp_server_registers_the_runtime_tools():
    """挂到真 FastMCP 上：名字、参数、描述都得在。

    这一步放在包自己的测试里跑：它要 ``asyncio.run``，而仓库根目录那套用例跑在
    session 级 event_loop 下，``asyncio.run`` 会把那个循环掀掉。
    """
    import asyncio

    from karma_openclaw.server import build_app

    tools = {t.name: t for t in asyncio.run(build_app().list_tools())}
    for name in (
        "karma_runtime_bind_key",
        "karma_runtime_binding_status",
        "karma_runtime_await_activation",
    ):
        assert name in tools, f"MCP 没挂上 {name}"
    assert "activation_code" in (tools["karma_runtime_bind_key"].description or "")
