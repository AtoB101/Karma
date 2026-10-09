import httpx
from karma_mcp_server.backend_client import KarmaBackend
from karma_mcp_server.config import McpConfig
from karma_mcp_server.server import build_server


def _server(handler, *, runtime_key="KRM_RT_kid_secret"):
    be = KarmaBackend(
        McpConfig(runtime_base_url="http://karma.test"),
        runtime_key=runtime_key,
        agent_private_key_seed="",
        transport=httpx.MockTransport(handler),
        credential_fn=lambda name: "",
    )
    return build_server(McpConfig(runtime_base_url="http://karma.test"), backend=be)


def _tool(server, name):
    return server._tool_manager.get_tool(name).fn


async def test_unconfigured_connection_is_not_an_error():
    server = _server(lambda r: httpx.Response(500, json={}), runtime_key="")
    out = await _tool(server, "karma_get_connection_status")()
    assert out["ok"] is True
    assert out["connection"] == "unconfigured"


async def test_active_connection():
    payload = {
        "key_id": "kid",
        "karma_identity_id": "ident-1",
        "permissions": ["place_order"],
        "status": "active",
        "key_binding": "agent",
        "agent_public_key": "pk",
        "nonce_required": True,
    }
    server = _server(lambda r: httpx.Response(200, json=payload))
    out = await _tool(server, "karma_get_connection_status")()
    assert out["ok"] is True
    assert out["connection"] == "active"
    assert out["permissions"] == ["place_order"]
    assert out["key_fingerprint"]


async def test_pending_activation_carries_next_step():
    payload = {
        "key_id": "kid",
        "status": "active",
        "key_binding": "agent_pending",
        "activation_required": True,
        "activation_code_ttl_seconds": 180,
    }
    server = _server(lambda r: httpx.Response(200, json=payload))
    out = await _tool(server, "karma_get_connection_status")()
    assert out["connection"] == "pending_activation"
    assert "配对码" in out["next_step"]


async def test_tool_never_reports_success_on_failure():
    server = _server(
        lambda r: httpx.Response(
            403, json={"detail": "runtime key missing permission: place_order"}
        )
    )
    out = await _tool(server, "karma_get_authorization_status")()
    assert out["ok"] is False
    assert out["error"]["class"] == "forbidden"


async def test_authorization_status_computes_remaining():
    payload = {
        "key_id": "kid",
        "configured": True,
        "auto_enabled": True,
        "permissions": ["place_order"],
        "limits": {
            "per_order_auto_approve_usdc": 5.0,
            "per_order_hard_cap_usdc": 10.0,
            "daily_auto_usdc": 20.0,
            "daily_hard_cap_usdc": 30.0,
            "daily_used_usdc": 12.5,
        },
        "never_expires": True,
    }
    server = _server(lambda r: httpx.Response(200, json=payload))
    out = await _tool(server, "karma_get_authorization_status")()
    assert out["ok"] is True
    assert out["limits"]["remaining_today_usdc"] == 17.5


async def test_policy_tool_returns_boundaries():
    payload = {
        "key_id": "kid",
        "configured": True,
        "policy_version": 3,
        "boundaries": {"high_risk_mode": "always"},
        "rules_zh": ["每一笔都要确认"],
    }
    server = _server(lambda r: httpx.Response(200, json=payload))
    out = await _tool(server, "karma_get_policy")()
    assert out["ok"] is True
    assert out["boundaries"]["high_risk_mode"] == "always"
    assert out["rules_zh"] == ["每一笔都要确认"]


async def test_unexpected_exception_is_wrapped_not_raised():
    def boom(request):
        raise ValueError("surprise")

    server = _server(boom)
    out = await _tool(server, "karma_get_connection_status")()
    assert out["ok"] is False
    assert out["error"]["class"] == "backend"
