"""OpenClaw MCP 侧接入 Runtime Key：公钥绑定 + 逐请求签名 + 匹配码交给主人。

OpenClaw 包是装在 agent 进程里的，所以这一整套它自己得能完成：申请接入 → 把 8 位
匹配码交回主人 → 主人在操作台输码 → 之后每个请求带签名。这里钉住三件事：

* 它算的签名消息与服务端逐字一致（跨包比对，防漂移）；
* 服务端验签器认它签出来的请求（把签名真喂给 verify_signed_request 跑一遍）；
* 没确认接入之前它不乱发签名（服务端对未绑定的 key 带签名是 403）。
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import HTTPException

from karma_openclaw import http_client as oc_http
from karma_openclaw import runtime_tools
from karma_openclaw.agent_binding import agent_key_from_seed
from karma_openclaw.agent_binding import build_agent_request_message as oc_build_agent_request_message
from karma_openclaw.agent_binding import runtime_key_id as oc_runtime_key_id
from services import runtime_key_service as rks
from services.runtime_wallet import build_agent_request_message as server_build_agent_request_message

KEY_ID = "c" * 32
TOKEN = "KRM_RT_" + KEY_ID + "_" + "d" * 64
SEED = base64.b64encode(bytes(range(32, 64))).decode()
SIGNATURE_REQUIRED = "X-Karma-Agent-Signature header is required for this runtime key"


def _public_key(key) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode()


def _fake_ctx(public_key: str) -> rks.RuntimeKeyContext:
    return rks.RuntimeKeyContext(
        key_id=KEY_ID,
        karma_identity_id="kid_openclaw_test",
        profile_id=None,
        wallet_address="0x" + "2" * 40,
        permissions=["submit_receipt"],
        single_limit=10.0,
        daily_limit=100.0,
        expire_at=datetime.now(timezone.utc) + timedelta(days=1),
        agent_name="openclaw",
        status="active",
        key_binding="agent" if public_key else "service",
        agent_public_key=public_key or None,
        nonce_required=True,
    )


@pytest.fixture(autouse=True)
def _clean_signing_state(monkeypatch):
    """签名模式是进程级缓存：别让上一条用例的结论漏到下一条。"""
    oc_http.reset_signing_mode()
    for name in ("KARMA_AGENT_PRIVATE_KEY", "KARMA_AGENT_ID", "KARMA_RUNTIME_KEY"):
        monkeypatch.delenv(name, raising=False)
    yield
    oc_http.reset_signing_mode()


class _FakeClient:
    """按序吐预置响应，并记下每次请求的头与体。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, headers=None, content=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "content": content,
            }
        )
        return self._responses.pop(0)

    async def get(self, url, headers=None):
        return await self.request("GET", url, headers=headers)


def _response(status_code: int, payload: dict, path: str = "/runtime/permissions") -> httpx.Response:
    url = "http://localhost:8000" + path
    return httpx.Response(status_code, json=payload, request=httpx.Request("POST", url))


def _install(monkeypatch, responses) -> _FakeClient:
    client = _FakeClient(responses)
    monkeypatch.setattr(oc_http.httpx, "AsyncClient", lambda **kw: client)
    return client


def _env(monkeypatch) -> None:
    monkeypatch.setenv("KARMA_RUNTIME_KEY", TOKEN)
    monkeypatch.setenv("KARMA_AGENT_PRIVATE_KEY", SEED)


# ------------------------------------------------------- 消息格式跨包一致


def test_openclaw_and_server_agree_on_the_signed_message():
    kwargs = dict(
        key_id=KEY_ID,
        method="post",
        path="/runtime/submit-receipt",
        timestamp="2026-09-18T12:00:00Z",
        nonce="nonce-12345678",
        body_sha256=hashlib.sha256(b'{"a":1}').hexdigest(),
    )
    assert oc_build_agent_request_message(**kwargs) == server_build_agent_request_message(**kwargs)
    assert oc_runtime_key_id(TOKEN) == KEY_ID
    assert oc_runtime_key_id("KRM_RT_" + KEY_ID) == KEY_ID


# ------------------------------------------------------- 服务端认它签的请求


async def test_the_server_verifier_accepts_what_openclaw_signs(monkeypatch):
    _env(monkeypatch)
    oc_http._set_signing_mode(True)
    body = oc_http.runtime_json_body({"amount": 1.5})
    headers = oc_http.runtime_headers(method="POST", path="/runtime/submit-receipt", body=body)
    assert headers["X-Karma-Runtime-Key"] == TOKEN
    rks.verify_signed_request(
        ctx=_fake_ctx(_public_key(agent_key_from_seed(SEED))),
        method="POST",
        path="/runtime/submit-receipt",
        body=body,
        signature_b64=headers["X-Karma-Agent-Signature"],
        timestamp_header=headers["X-Karma-Runtime-Timestamp"],
        nonce_header=headers["X-Karma-Runtime-Nonce"],
    )


async def test_the_signature_is_bound_to_the_exact_body(monkeypatch):
    _env(monkeypatch)
    oc_http._set_signing_mode(True)
    headers = oc_http.runtime_headers(
        method="POST", path="/runtime/submit-receipt", body=b'{"amount":1.5}'
    )
    with pytest.raises(HTTPException) as excinfo:
        rks.verify_signed_request(
            ctx=_fake_ctx(_public_key(agent_key_from_seed(SEED))),
            method="POST",
            path="/runtime/submit-receipt",
            body=b'{"amount":9999}',  # 换个体，签名就不再对得上
            signature_b64=headers["X-Karma-Agent-Signature"],
            timestamp_header=headers["X-Karma-Runtime-Timestamp"],
            nonce_header=headers["X-Karma-Runtime-Nonce"],
        )
    assert excinfo.value.status_code == 401


async def test_signing_an_unbound_key_is_the_one_thing_we_must_not_do(monkeypatch):
    """未绑定的 key 带签名，服务端直接 403 —— 所以签名开关默认必须关着。"""
    _env(monkeypatch)
    headers = oc_http.runtime_headers(method="GET", path="/runtime/permissions")
    assert "X-Karma-Agent-Signature" not in headers
    with pytest.raises(HTTPException) as excinfo:
        rks.verify_signed_request(
            ctx=_fake_ctx(""),
            method="GET",
            path="/runtime/permissions",
            body=b"",
            signature_b64="Zm9v",
            timestamp_header=headers["X-Karma-Runtime-Timestamp"]
            if "X-Karma-Runtime-Timestamp" in headers
            else "2026-09-18T12:00:00Z",
            nonce_header="nonce",
        )
    assert excinfo.value.status_code == 403


# ------------------------------------------------------- 探一次就知道要不要签


async def test_probe_turns_signing_on_when_the_server_demands_a_signature(monkeypatch):
    _env(monkeypatch)
    client = _install(monkeypatch, [_response(401, {"detail": SIGNATURE_REQUIRED})])
    assert await oc_http.refresh_signing_mode() is True
    assert oc_http.signing_mode() is True
    assert len(client.calls) == 1
    assert "X-Karma-Agent-Signature" not in client.calls[0]["headers"]


async def test_probe_stays_off_while_the_key_is_still_waiting_for_the_code(monkeypatch):
    _env(monkeypatch)
    _install(
        monkeypatch,
        [_response(200, {"key_binding": "agent_pending", "activation_required": True})],
    )
    assert await oc_http.refresh_signing_mode() is False


async def test_probe_stays_off_for_a_bearer_key_that_can_no_longer_spend(monkeypatch):
    _env(monkeypatch)
    _install(
        monkeypatch,
        [_response(403, {"detail": "this runtime key is a bearer key minted without an agent binding"})],
    )
    assert await oc_http.refresh_signing_mode() is False


async def test_without_an_agent_key_we_never_sign(monkeypatch):
    monkeypatch.setenv("KARMA_RUNTIME_KEY", TOKEN)
    assert await oc_http.refresh_signing_mode() is False


# ------------------------------------------------------- 请求路径


async def test_a_call_retries_with_a_signature_once_activation_lands(monkeypatch):
    """主人刚输完匹配码：这次调用探到 401「要签名」，补签重发一次就成了。"""
    _env(monkeypatch)
    client = _install(
        monkeypatch,
        [
            _response(200, {"key_binding": "agent_pending"}),
            _response(401, {"detail": SIGNATURE_REQUIRED}, "/runtime/submit-receipt"),
            _response(200, {"ok": True}, "/runtime/submit-receipt"),
        ],
    )
    assert await oc_http.runtime_post("/runtime/submit-receipt", {"a": 1}) == {"ok": True}
    assert [c["headers"].get("X-Karma-Agent-Signature") is not None for c in client.calls] == [
        False,
        False,
        True,
    ]


async def test_the_server_wording_survives_into_the_raised_error(monkeypatch):
    _env(monkeypatch)
    _install(
        monkeypatch,
        [
            _response(200, {"key_binding": "service"}),
            _response(403, {"detail": "this runtime key is a bearer key minted without an agent binding"}, "/runtime/capacity"),
        ],
    )
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        await oc_http.runtime_post("/runtime/capacity", {})
    assert "bearer key" in str(excinfo.value)


# ------------------------------------------------------- 匹配码交给主人


async def test_bind_key_hands_the_matching_code_back_to_the_owner(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("KARMA_AGENT_ID", "openclaw-1")
    captured: dict = {}

    async def fake_post(path, body):
        captured["path"] = path
        captured["body"] = body
        return {
            "status": "pending_activation",
            "agent_id": "openclaw-1",
            "activation_code": "K7Q2-M4XP",
            "activation_expires_at": "2026-09-18T12:03:00Z",
            "activation_attempts_left": 5,
            "pending_binding": {"agent_fingerprint": "ab" * 8},
        }

    monkeypatch.setattr(runtime_tools, "runtime_post", fake_post)
    out = await runtime_tools.karma_runtime_bind_key()
    assert captured["path"] == "/runtime/bind-key"
    assert captured["body"]["agent_id"] == "openclaw-1"
    assert captured["body"]["agent_public_key"] == _public_key(agent_key_from_seed(SEED))
    assert captured["body"]["client_nonce"]
    assert out["ok"] is True
    assert out["status"] == "pending_activation"
    assert out["activation_code"] == "K7Q2-M4XP"
    assert "K7Q2-M4XP" in out["hand_to_owner"]
    assert out["pending_binding"] == {"agent_fingerprint": "ab" * 8}


async def test_bind_key_asks_the_server_which_agent_this_key_names(monkeypatch):
    _env(monkeypatch)
    monkeypatch.delenv("KARMA_AGENT_ID", raising=False)
    captured: dict = {}

    async def fake_get(path):
        return {"agent_binding": "openclaw-9"}

    async def fake_post(path, body):
        captured["body"] = body
        return {"status": "pending_activation", "activation_code": "AAAA-BBBB"}

    monkeypatch.setattr(runtime_tools, "runtime_get", fake_get)
    monkeypatch.setattr(runtime_tools, "runtime_post", fake_post)
    out = await runtime_tools.karma_runtime_bind_key()
    assert captured["body"]["agent_id"] == "openclaw-9"
    assert out["activation_code"] == "AAAA-BBBB"


async def test_bind_key_without_a_private_key_says_so(monkeypatch):
    monkeypatch.setenv("KARMA_RUNTIME_KEY", TOKEN)
    out = await runtime_tools.karma_runtime_bind_key()
    assert out["ok"] is False
    assert out["error"] == "agent_private_key_missing"


async def test_bind_key_surfaces_the_server_reason(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("KARMA_AGENT_ID", "openclaw-1")

    async def fake_post(path, body):
        raise httpx.HTTPStatusError("403", request=httpx.Request("POST", "http://x/y"), response=httpx.Response(403))

    monkeypatch.setattr(runtime_tools, "runtime_post", fake_post)
    out = await runtime_tools.karma_runtime_bind_key()
    assert out["ok"] is False
    assert out["error"] == "bind_key_failed"


async def test_binding_status_reports_where_this_key_stands(monkeypatch):
    _env(monkeypatch)
    async def fake_refresh():
        return True
    async def fake_get(path):
        return {
            "key_binding": "agent",
            "agent_binding": "openclaw-1",
            "agent_fingerprint": "cd" * 8,
            "permissions": ["submit_receipt"],
            "pending_binding": None,
        }
    monkeypatch.setattr(runtime_tools, "refresh_signing_mode", fake_refresh)
    monkeypatch.setattr(runtime_tools, "runtime_get", fake_get)
    out = await runtime_tools.karma_runtime_binding_status()
    assert out["ok"] is True
    assert out["signed_requests"] is True
    assert out["key_binding"] == "agent"
    assert out["permissions"] == ["submit_receipt"]


async def test_await_activation_confirms_and_flips_signing_on(monkeypatch):
    _env(monkeypatch)
    async def fake_refresh():
        return True
    async def fake_get(path):
        return {"key_binding": "agent", "agent_binding": "openclaw-1", "permissions": ["submit_receipt"]}
    monkeypatch.setattr(runtime_tools, "refresh_signing_mode", fake_refresh)
    monkeypatch.setattr(runtime_tools, "runtime_get", fake_get)
    out = await runtime_tools.karma_runtime_await_activation(timeout_seconds=0)
    assert out == {
        "ok": True,
        "status": "active",
        "key_binding": "agent",
        "agent_binding": "openclaw-1",
        "permissions": ["submit_receipt"],
    }


async def test_await_activation_gives_up_with_a_pending_verdict(monkeypatch):
    _env(monkeypatch)
    async def fake_refresh():
        return False
    monkeypatch.setattr(runtime_tools, "refresh_signing_mode", fake_refresh)
    out = await runtime_tools.karma_runtime_await_activation(timeout_seconds=0)
    assert out["ok"] is False
    assert out["status"] == "pending"
    assert out["error"] == "activation_timeout"


def test_the_mcp_registers_the_three_runtime_tools():
    """注册这一步单独钉一下。

    这里**不能**用 ``asyncio.run(build_app().list_tools())`` 去验：``asyncio.run``
    结束时会 ``set_event_loop(None)``，把 conftest 那个 session 级 event_loop 掀掉，
    整个会话后面所有 async 用例会集体变成「coroutine was never awaited」。
    「真的挂上 FastMCP 了」交给包自己的测试（packages/karma-openclaw/tests）去跑。
    """

    class _FakeMcp:
        def __init__(self) -> None:
            self.tools: list = []

        def add_tool(self, fn) -> None:
            self.tools.append(fn)

    mcp = _FakeMcp()
    runtime_tools.register_runtime_tools(mcp)
    assert [fn.__name__ for fn in mcp.tools] == [
        "karma_runtime_bind_key",
        "karma_runtime_binding_status",
        "karma_runtime_await_activation",
    ]
