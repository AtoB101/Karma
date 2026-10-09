"""端到端接线测试（S3 配对/授权 + S4 远程鉴权 + 启动红线）。

全走 ``httpx.MockTransport``，按真实后端契约（``services/agent_pairing.py``、
``api/routes/runtime_gateway.py``）打桩，钉住四件事：

1. ``pairing_code`` 只落本机 0600 文件，任何工具返回值里都不出现。
2. 领凭据只回指纹与路径，明文凭据永不回显；agent 私钥不会被冲掉。
3. 授权写入必须由主人钱包签名 —— MCP 只原样转交签名，绝不代签。
4. 启动红线：注入私钥 / 远程无令牌 / 远程未开启，一律拒绝启动。
"""

from __future__ import annotations

import json

import httpx
from karma_mcp_server.backend_client import KarmaBackend
from karma_mcp_server.config import McpConfig
from karma_mcp_server.redact import fingerprint
from karma_mcp_server.server import build_server

PAIRING_CODE = "PC-SUPER-SECRET-9x"
RUNTIME_KEY = "KRM_RT_kid9_secretpart"
API_KEY = "KRM_API_agent9_apisecret"
WALLET = "0x1234567890abcdef1234567890abcdef12345678"


def _make(handler, *, runtime_key=RUNTIME_KEY):
    backend = KarmaBackend(
        McpConfig(runtime_base_url="http://karma.test"),
        runtime_key=runtime_key,
        agent_private_key_seed="",
        transport=httpx.MockTransport(handler),
        credential_fn=lambda name: "",
    )
    return build_server(McpConfig(runtime_base_url="http://karma.test"), backend=backend)


def _tool(server, name):
    return server._tool_manager.get_tool(name).fn


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("KARMA_MCP_STATE_DIR", str(tmp_path / "pairings"))
    env_path = tmp_path / "agent.env"
    monkeypatch.setenv("KARMA_AGENT_ENV_PATH", str(env_path))
    return env_path


async def test_pairing_claim_writes_credentials_without_echoing_them(tmp_path, monkeypatch):
    env_path = _isolate(tmp_path, monkeypatch)
    calls: list[dict] = []

    def handler(request):
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        calls.append({"path": path, "body": body})
        if path == "/v1/agent-pairing/request":
            assert body["agent_name"] == "小爱"
            assert body.get("public_key")  # 申请时就交公钥，配对即激活
            return httpx.Response(
                200,
                json={
                    "pairing_code": PAIRING_CODE,
                    "user_code": "K4QP-3M2X",
                    "verification_uri": "https://console.karma.test/pair",
                    "expires_at": "2026-10-10T00:05:00Z",
                    "poll_interval_seconds": 3,
                },
            )
        if path == "/v1/agent-pairing/claim":
            assert body["pairing_code"] == PAIRING_CODE
            return httpx.Response(
                200,
                json={
                    "status": "approved",
                    "agent_id": "agent-9",
                    "owner_identity_id": "ident-1",
                    "credentials": {
                        "api_key": API_KEY,
                        "runtime_key": RUNTIME_KEY,
                        "runtime_key_id": "kid9",
                    },
                    "env_snippet": {
                        "KARMA_AGENT_ID": "agent-9",
                        "KARMA_RUNTIME_URL": "http://karma.test",
                        "KARMA_API_KEY": API_KEY,
                        "KARMA_RUNTIME_KEY": RUNTIME_KEY,
                    },
                },
            )
        raise AssertionError("unexpected path " + path)

    server = _make(handler)

    started = await _tool(server, "karma_connect")(agent_name="小爱")
    assert started["ok"] is True
    assert started["status"] == "pending_owner"
    assert started["user_code"] == "K4QP-3M2X"
    assert PAIRING_CODE not in json.dumps(started, ensure_ascii=False)

    state_files = list((tmp_path / "pairings").glob("*.json"))
    assert len(state_files) == 1
    assert PAIRING_CODE in state_files[0].read_text(encoding="utf-8")

    status = await _tool(server, "karma_connect_status")()
    assert status["ok"] is True
    assert status["pairing"] == "pending_owner"
    assert PAIRING_CODE not in json.dumps(status, ensure_ascii=False)
    # 查状态绝不能再打网络：那一步会把一次性凭据吃掉
    assert [c["path"] for c in calls] == ["/v1/agent-pairing/request"]

    claimed = await _tool(server, "karma_connect_claim")()
    assert claimed["ok"] is True
    assert claimed["status"] == "claimed"
    assert claimed["agent_id"] == "agent-9"
    assert claimed["owner_identity_id"] == "ident-1"
    echoed = json.dumps(claimed, ensure_ascii=False)
    assert PAIRING_CODE not in echoed
    assert RUNTIME_KEY not in echoed and API_KEY not in echoed
    assert claimed["credentials"]["api_key"]["fingerprint"] == fingerprint(API_KEY)
    assert claimed["credentials"]["runtime_key"]["fingerprint"] == fingerprint(RUNTIME_KEY)
    assert claimed["credentials"]["runtime_key"]["runtime_key_id"] == "kid9"

    written = env_path.read_text(encoding="utf-8")
    assert "KARMA_RUNTIME_KEY=" + RUNTIME_KEY in written
    assert "KARMA_API_KEY=" + API_KEY in written
    # 配对时生成的 agent 私钥不能被这次改写冲掉
    assert "KARMA_AGENT_PRIVATE_KEY=" in written
    assert str(env_path) == claimed["env_path"]


async def test_authorization_is_signed_by_owner_wallet_not_by_mcp():
    seen: dict = {}

    def handler(request):
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        seen["path"] = path
        seen["body"] = body
        if path == "/runtime/create-key":
            return httpx.Response(
                200,
                json={
                    "key_id": "kid-new",
                    "runtime_key": "KRM_RT_kid-new_secret",
                    "permissions": body["permissions"],
                    "single_limit": body["single_limit"],
                    "daily_limit": body["daily_limit"],
                },
            )
        raise AssertionError("unexpected path " + path)

    server = _make(handler)

    preview = await _tool(server, "karma_request_authorization")(
        permissions=["place_order"],
        single_limit=5.0,
        daily_limit=20.0,
        agent_name="小爱",
        karma_identity_id="ident-1",
        wallet_address=WALLET,
    )
    assert preview["ok"] is True
    assert preview["step"] == "awaiting_wallet_signature"
    message = preview["sign_message"]
    assert message.splitlines()[0] == "Karma Runtime Key Create"
    assert "karma_identity_id:ident-1" in message
    assert "wallet_address:" + WALLET in message
    assert "permissions:place_order" in message
    assert "daily_limit:20.0" in message
    assert seen == {}  # 预览不写后端、不发网络

    submitted = await _tool(server, "karma_submit_authorization")(
        wallet_signature="0xowner-sig",
        agent_name="小爱",
        wallet_address=WALLET,
        permissions=["place_order"],
        single_limit=5.0,
        daily_limit=20.0,
        karma_identity_id="ident-1",
    )
    assert submitted["ok"] is True
    assert submitted["key_id"] == "kid-new"
    assert submitted["delivered"] is True
    assert "KRM_RT_kid-new_secret" not in json.dumps(submitted, ensure_ascii=False)

    sent = seen["body"]
    assert seen["path"] == "/runtime/create-key"
    assert sent["wallet_signature"] == "0xowner-sig"
    assert sent["permissions"] == ["place_order"]
    assert sent["single_limit"] == 5.0
    assert sent["daily_limit"] == 20.0
    assert sent["wallet_address"] == WALLET


async def test_revoke_preview_then_execute():
    seen: dict = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "revoked", "key_id": "kid-old"})

    server = _make(handler)

    preview = await _tool(server, "karma_revoke_authorization")(
        key_id="kid-old", karma_identity_id="ident-1", wallet_address=WALLET
    )
    assert preview["ok"] is True
    assert preview["step"] == "awaiting_wallet_signature"
    assert "key_id:kid-old" in preview["sign_message"]
    assert seen == {}

    done = await _tool(server, "karma_revoke_authorization")(
        key_id="kid-old",
        karma_identity_id="ident-1",
        wallet_address=WALLET,
        wallet_signature="0xrevoke-sig",
        twofa_code="123456",
    )
    assert done["ok"] is True
    assert seen["path"] == "/runtime/revoke-key"
    assert seen["body"]["wallet_signature"] == "0xrevoke-sig"
    assert seen["body"]["twofa_code"] == "123456"


def test_cli_refuses_forbidden_private_key(monkeypatch, capsys):
    from karma_mcp_server.__main__ import main

    monkeypatch.setenv("KARMA_PRIVATE_KEY", "0xdeadbeef")
    assert main(["--transport", "stdio"]) == 2
    assert "must not hold private key material" in capsys.readouterr().err


def test_cli_refuses_remote_transport_when_disabled(monkeypatch):
    from karma_mcp_server.__main__ import main

    monkeypatch.delenv("KARMA_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("KARMA_MCP_ENABLE_HTTP", raising=False)
    assert main(["--transport", "streamable-http"]) == 3


def test_cli_refuses_remote_without_token(monkeypatch):
    from karma_mcp_server.__main__ import main

    monkeypatch.delenv("KARMA_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("KARMA_MCP_ENABLE_HTTP", "1")
    monkeypatch.delenv("KARMA_MCP_HTTP_TOKEN", raising=False)
    assert main(["--transport", "streamable-http"]) == 4
