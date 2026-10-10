"""Tier 2/3 接线测试：默认 fail-closed 不注册；开启后参数契约与真实后端对齐。"""
from __future__ import annotations

import json

import httpx
from karma_mcp_server.backend_client import KarmaBackend
from karma_mcp_server.config import McpConfig
from karma_mcp_server.server import build_server

RUNTIME_KEY = "KRM_RT_kid23_secret"
API_KEY = "karma_agent23_apisecret"


def _backend(handler, *, runtime_key=RUNTIME_KEY):
    return KarmaBackend(
        McpConfig(runtime_base_url="http://karma.test"),
        runtime_key=runtime_key,
        api_key=API_KEY,
        agent_private_key_seed="",
        transport=httpx.MockTransport(handler),
        credential_fn=lambda name: "",
    )


def _server(handler=None, *, t2=True, t3=True, runtime_key=RUNTIME_KEY):
    cfg = McpConfig(runtime_base_url="http://karma.test", enable_tier2=t2, enable_tier3=t3)
    be = _backend(
        handler or (lambda r: httpx.Response(200, json={})), runtime_key=runtime_key
    )
    return build_server(cfg, backend=be)


def _tool(server, name):
    return server._tool_manager.get_tool(name).fn


def _names(server):
    return {t.name for t in server._tool_manager.list_tools()}


def _schema(server, name):
    """工具对外暴露的入参 JSON Schema（MCP 客户端在调用前就会照它校验）。"""
    return server._tool_manager.get_tool(name).parameters


TIER23 = {
    "karma_create_transaction",
    "karma_accept_payment_code",
    "karma_decide_confirmation",
    "karma_submit_evidence",
    "karma_verify_evidence",
    "karma_submit_receipt",
    "karma_submit_progress",
    "karma_request_settlement",
    "karma_verify_voucher",
    "karma_open_dispute",
    "karma_request_refund",
}


def test_tier23_not_registered_by_default():
    """T2/T3 默认关闭 —— fail-closed，不注册就不可能出现。"""
    assert not (TIER23 & _names(_server(t2=False, t3=False)))


def test_tier2_only_leaves_tier3_out():
    names = _names(_server(t3=False))
    assert "karma_create_transaction" in names
    assert "karma_accept_payment_code" in names
    assert "karma_open_dispute" not in names
    assert "karma_request_refund" not in names
    assert "karma_verify_voucher" not in names


def test_tier23_registered_when_enabled():
    assert TIER23 <= _names(_server())


async def test_tier2_write_fails_closed_without_runtime_key():
    """没有 Runtime Key 时，T2 写工具直接 unauthorized，绝不裸奔到后端。"""
    server = _server(runtime_key=None)
    out = await _tool(server, "karma_create_transaction")(
        requirement_text="buy a widget", amount=1.0, client_nonce="nonce-12345678"
    )
    assert out["ok"] is False
    assert out["error"]["class"] == "unauthorized"


async def test_accept_payment_code_requires_and_sends_seller_identity():
    seen: dict = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content) if request.content else {}
        return httpx.Response(200, json={"voucher_id": "v-1"})

    server = _server(handler)

    required = _schema(server, "karma_accept_payment_code")["required"]
    assert "seller_identity_id" in required

    bad = await _tool(server, "karma_accept_payment_code")(
        voucher_id="v-1", seller_identity_id=""
    )
    assert bad["ok"] is False
    assert bad["error"]["class"] == "invalid"
    assert seen == {}

    out = await _tool(server, "karma_accept_payment_code")(
        voucher_id="v-1", seller_identity_id="ident-seller", seller_profile_id="card-7"
    )
    assert out["ok"] is True
    assert seen["path"] == "/v1/payment-codes/v-1/accept"
    assert seen["body"] == {
        "seller_identity_id": "ident-seller",
        "seller_profile_id": "card-7",
    }


async def test_verify_evidence_needs_expected_digest():
    seen: dict = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content) if request.content else {}
        return httpx.Response(200, json={"verified": True})

    server = _server(handler)

    required = _schema(server, "karma_verify_evidence")["required"]
    assert "expected_digest_sha256" in required

    bad = await _tool(server, "karma_verify_evidence")(
        evidence_id="e-1", expected_digest_sha256=""
    )
    assert bad["ok"] is False
    assert bad["error"]["class"] == "invalid"
    assert seen == {}

    out = await _tool(server, "karma_verify_evidence")(
        evidence_id="e-1",
        expected_digest_sha256="abc123",
        expected_schema_version="karma-evidence-v1",
    )
    assert out["ok"] is True
    assert seen["path"] == "/v1/evidence/e-1/verify"
    assert seen["body"] == {
        "expectedDigestSha256": "abc123",
        "expectedSchemaVersion": "karma-evidence-v1",
    }


async def test_get_voucher_only_reads_events_with_identity():
    seen: list = []

    def handler(request):
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"voucher_id": "v-9"})

    server = _server(handler, runtime_key=None)

    out = await _tool(server, "karma_get_voucher")(voucher_id="v-9")
    assert out["ok"] is True
    assert [p for p, _ in seen] == ["/v1/vouchers/v-9"]
    assert out["events"] is None
    assert "events_note" in out

    seen.clear()
    out2 = await _tool(server, "karma_get_voucher")(voucher_id="v-9", identity_id="ident-b")
    assert out2["ok"] is True
    assert [p for p, _ in seen] == ["/v1/vouchers/v-9", "/v1/vouchers/v-9/events"]
    assert seen[1][1] == {"identity_id": "ident-b"}


async def test_dispute_and_refund_share_the_single_frozen_entry():
    seen: list = []

    def handler(request):
        seen.append(
            (request.url.path, json.loads(request.content) if request.content else {})
        )
        return httpx.Response(200, json={"status": "disputed"})

    server = _server(handler)

    out = await _tool(server, "karma_open_dispute")(
        task_id="t-1", reason="not as described", reason_code="QUALITY_OBJECTIVE_FAIL"
    )
    assert out["ok"] is True
    assert seen[-1] == (
        "/v1/settlement/t-1/dispute",
        {"reason": "not as described", "reason_code": "QUALITY_OBJECTIVE_FAIL"},
    )

    out2 = await _tool(server, "karma_request_refund")(task_id="t-1", reason="want money back")
    assert out2["ok"] is True
    assert seen[-1] == ("/v1/settlement/t-1/dispute", {"reason": "want money back"})


async def test_dispute_requires_task_id():
    server = _server(lambda r: httpx.Response(200, json={}))
    out = await _tool(server, "karma_open_dispute")(task_id="")
    assert out["ok"] is False
    assert out["error"]["class"] == "invalid"