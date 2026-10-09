"""钱包 / agent 签名文案的多份副本必须逐字一致（服务端是唯一真源）。

同一段文字在仓库里有好几份实现：服务端 ``services/runtime_wallet.py``、SDK
``sdk/runtime_client.py``、MCP 包、OpenClaw 包、示例场景包。任何一份漂移，表现都是
「签名看起来完全正确，服务端却 403」—— 最难查的那种故障。所以每一份都在这里和服务端
那唯一真源逐字对齐。

新增/改动签名文案时，先改服务端，再让本文件告诉你还有哪几份没跟上。
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

CREATE_KEY_KW = {
    "karma_identity_id": "ident-1",
    "wallet_address": "0xAbC0000000000000000000000000000000000001",
    "permissions": ["request_voucher", "place_order"],
    "single_limit": 5.0,
    "daily_limit": 20.0,
    "expire_time": None,
    "agent_name": "claw-1",
    "agent_binding": "agent-9",
    "agent_public_key_fingerprint": "a1b2c3d4e5f60718",
}

PAIRING_KW = {
    "agent_name": "claw-1",
    "public_key": "K0fQ1oQ0kZ9Z0o1nS0m9zq3Rk0kQ9mT1P0o2s3d4f5g=",
    "nonce": "0f9a1b2c3d4e5f60",
    "timestamp": "2026-10-10T00:00:00Z",
}

REQUEST_KW = {
    "key_id": "kid-1",
    "method": "POST",
    "path": "/runtime/place-order",
    "timestamp": "2026-10-10T00:00:00Z",
    "nonce": "0f9a1b2c3d4e5f60",
    "body_sha256": "ab" * 32,
}


def _add_path(rel: str) -> None:
    path = str(ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)


def _load_file(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def server_wallet():
    return importlib.import_module("services.runtime_wallet")


@pytest.fixture(scope="module")
def mcp_wallet():
    _add_path("packages/karma-mcp-server")
    return importlib.import_module("karma_mcp_server.wallet_messages")


@pytest.fixture(scope="module")
def mcp_signing():
    _add_path("packages/karma-mcp-server")
    return importlib.import_module("karma_mcp_server.agent_signing")


def test_mcp_create_key_message_matches_server(server_wallet, mcp_wallet):
    assert mcp_wallet.build_create_key_message(**CREATE_KEY_KW) == (
        server_wallet.build_create_key_message(**CREATE_KEY_KW)
    )


def test_mcp_revoke_key_message_matches_server(server_wallet, mcp_wallet):
    kw = {"key_id": "kid-1", "karma_identity_id": "ident-1", "wallet_address": "0xabc"}
    assert mcp_wallet.build_revoke_key_message(**kw) == server_wallet.build_revoke_key_message(**kw)


def test_mcp_agent_request_message_matches_server(server_wallet, mcp_signing):
    assert mcp_signing.build_agent_request_message(**REQUEST_KW) == (
        server_wallet.build_agent_request_message(**REQUEST_KW)
    )


def test_mcp_pairing_request_message_matches_server(server_wallet, mcp_signing):
    assert mcp_signing.build_agent_pairing_request_message(**PAIRING_KW) == (
        server_wallet.build_agent_pairing_request_message(**PAIRING_KW)
    )


def test_sdk_pairing_request_message_matches_server(server_wallet):
    sdk = importlib.import_module("sdk.runtime_client")
    assert sdk.build_agent_pairing_request_message(**PAIRING_KW) == (
        server_wallet.build_agent_pairing_request_message(**PAIRING_KW)
    )


def test_openclaw_pairing_request_message_matches_server(server_wallet):
    _add_path("packages/karma-openclaw")
    binding = importlib.import_module("karma_openclaw.agent_binding")
    assert binding.build_agent_pairing_request_message(**PAIRING_KW) == (
        server_wallet.build_agent_pairing_request_message(**PAIRING_KW)
    )


def test_example_pack_create_key_message_matches_server(server_wallet):
    flow = _load_file("examples/scenario-packs/_lib/karma_flow.py", "_karma_flow_parity")
    # 场景包那份只接受真正的 datetime（它不做 "never" 那个分支），所以换一个有值有效期。
    kw = {**CREATE_KEY_KW, "expire_time": datetime(2026, 11, 1, tzinfo=UTC)}
    assert flow.build_create_key_message(**kw) == (
        server_wallet.build_create_key_message(**kw)
    )


def test_create_key_message_carries_the_fingerprint_line(server_wallet):
    """指纹不是注释：它必须真的出现在签名文字里，且随值变化。"""
    signed = server_wallet.build_create_key_message(**CREATE_KEY_KW)
    assert "agent_public_key_fingerprint:a1b2c3d4e5f60718" in signed
    blank = server_wallet.build_create_key_message(
        **{**CREATE_KEY_KW, "agent_public_key_fingerprint": None}
    )
    assert blank.endswith("agent_public_key_fingerprint:")
    assert blank != signed
