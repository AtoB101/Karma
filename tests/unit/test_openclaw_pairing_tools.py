# -*- coding: utf-8 -*-
"""OpenClaw MCP 侧自助配接：自己申请、自己把凭据落到本机，聊天里不留密钥。

配对接入是两把锁（`docs/AGENT_PAIRING_V1.md`）：agent 自己的 `pairing_code` 证明
「你就是当初申请的那个进程」，主人当场签发的 `handoff_code` 证明「主人真的把凭据
交到了你手上」。这里钉住 agent 侧的三件事：

* 申请时拿到的 `pairing_code` 只落盘 0600，**不进聊天**；
* 没有交接码时它老实说「等主人签发」，绝不假装成功；
* 拿到凭据后只回指纹，明文只写进 `~/.karma/agent.env`。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import stat

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from karma_openclaw import pairing_tools as pt
from karma_openclaw.agent_binding import build_agent_pairing_request_message

USER_CODE = "QKFS-3J5Z"
PAIRING_CODE = "pc-" + "a" * 40
API_KEY = "karma_agent-1b4bb344ebfb_" + "b" * 32
RUNTIME_KEY = "KRM_RT_" + "c" * 32 + "_" + "d" * 64


def _fp(secret: str) -> str:
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("KARMA_PAIRING_STATE_DIR", str(tmp_path / "pairing"))
    monkeypatch.setenv("KARMA_AGENT_ENV_PATH", str(tmp_path / "karma" / "agent.env"))
    monkeypatch.setenv("KARMA_RUNTIME_URL", "https://karma-network.ai")
    yield


def _install(monkeypatch, responses):
    """按序吐预置响应，并记下每次 POST 的路径与请求体。"""
    calls: list[dict] = []

    async def fake_post(path, body):
        calls.append({"path": path, "body": body})
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(pt, "api_post", fake_post)
    return calls


def _request_payload() -> dict:
    return {
        "pairing_code": PAIRING_CODE,
        "user_code": USER_CODE,
        "verification_uri": "https://karma-network.ai/console/?pair=" + USER_CODE,
        "expires_at": "2026-09-25T12:00:00Z",
        "poll_interval_seconds": 3,
        "claim_endpoint": "/v1/agent-pairing/claim",
    }


def _approved_payload() -> dict:
    return {
        "schema_version": "karma-agent-pairing-claim-v1",
        "status": "approved",
        "agent_id": "agent-1b4bb344ebfb",
        "owner_identity_id": "kid_owner000000000001",
        "handoff": {"required": True, "consumed": True},
        "credentials": {
            "api_key": API_KEY,
            "agent_public_key": "ed25519:AAAA",
            "runtime_key": RUNTIME_KEY,
            "runtime_key_id": "c" * 32,
            "store_now": True,
        },
        "env_snippet": {
            "KARMA_AGENT_ID": "agent-1b4bb344ebfb",
            "KARMA_RUNTIME_URL": "https://karma-network.ai",
            "KARMA_API_KEY": API_KEY,
            "KARMA_RUNTIME_KEY": RUNTIME_KEY,
        },
    }


def _http_error(status_code: int, detail: str) -> httpx.HTTPStatusError:
    resp = httpx.Response(
        status_code,
        json={"detail": detail},
        request=httpx.Request("POST", "https://karma-network.ai/v1/agent-pairing/claim"),
    )
    return httpx.HTTPStatusError(f"{status_code}", request=resp.request, response=resp)


def _env_text() -> str:
    """凭据文件的正文（不存在就是空串）。"""
    path = pt.agent_env_path()
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _state_files() -> list:
    directory = pt.pairing_state_dir()
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


# --------------------------------------------------------------- 申请


async def test_start_saves_the_pairing_code_locally_and_never_echoes_it(monkeypatch):
    calls = _install(monkeypatch, [_request_payload()])
    out = await pt.karma_pairing_start("claw-001", requested_side="seller", requested_vertical="food")

    assert calls[0]["path"] == "/v1/agent-pairing/request"
    assert calls[0]["body"]["agent_name"] == "claw-001"
    assert calls[0]["body"]["requested_side"] == "seller"
    # 顺带把自己的公钥一起交上去：主人在操作台核对过指纹之后，批准那一下就能把
    # Runtime Key 钉在它上面（配对即激活），不用再来一轮 8 位匹配码。
    pub = calls[0]["body"]["public_key"]
    assert len(pub) == 44 and pub.endswith("=")
    # 公钥不是「申报」而是「持有证明」：请求体里必须带上用本机私钥签的签名。
    body = calls[0]["body"]
    assert body["signature"] and body["nonce"] and body["timestamp"]
    message = build_agent_pairing_request_message(
        agent_name=body["agent_name"],
        public_key=pub,
        nonce=body["nonce"],
        timestamp=body["timestamp"],
    )
    Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(
        base64.b64decode(body["signature"]), message.encode("utf-8")
    )

    assert out["ok"] is True
    assert out["status"] == "pending_owner"
    assert out["user_code"] == USER_CODE
    assert "QKFS-3J5Z" in out["hand_to_owner"]
    assert out["verification_uri"].endswith("?pair=" + USER_CODE)
    # 关键：pairing_code 只落盘，不能出现在返回值里。
    assert PAIRING_CODE not in json.dumps(out, ensure_ascii=False)

    files = _state_files()
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved["pairing_code"] == PAIRING_CODE
    assert saved["user_code"] == USER_CODE
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(files[0]).st_mode) == 0o600


async def test_start_refuses_a_nameless_agent_without_calling_the_server(monkeypatch):
    calls = _install(monkeypatch, [])
    out = await pt.karma_pairing_start("   ")
    assert out["ok"] is False
    assert out["error"] == "agent_name_required"
    assert calls == []


async def test_start_surfaces_the_server_reason(monkeypatch):
    _install(monkeypatch, [_http_error(429, "too many pending pairings from this IP")])
    out = await pt.karma_pairing_start("claw-001")
    assert out["ok"] is False
    assert out["error"] == "pairing_request_failed"
    assert "too many pending" in out["detail"]


# --------------------------------------------------------------- 领取


async def test_claim_relays_the_handoff_ask_the_server_reports(monkeypatch):
    _install(monkeypatch, [
        _request_payload(),
        {
            "status": "awaiting_handoff",
            "handoff_state": "none",
            "expires_at": "2026-09-25T12:00:00Z",
            "poll_interval_seconds": 3,
        },
    ])
    await pt.karma_pairing_start("claw-001")
    out = await pt.karma_pairing_claim()

    assert out["ok"] is False
    assert out["status"] == "awaiting_handoff"
    assert out["handoff_state"] == "none"
    assert "签发交接码" in out["ask_owner"]


async def test_claim_lets_the_server_explain_the_hold(monkeypatch):
    """服务端的话是权威：它说为什么卡住，agent 就照搬，不自己编。"""
    _install(monkeypatch, [
        _request_payload(),
        {
            "status": "awaiting_handoff",
            "handoff_state": "none",
            "message_zh": "这次部署仍要求交接码：请主人在操作台签发后再试。",
            "expires_at": "2026-09-25T12:00:00Z",
            "poll_interval_seconds": 3,
        },
    ])
    await pt.karma_pairing_start("claw-001")
    out = await pt.karma_pairing_claim()
    assert out["ask_owner"] == "这次部署仍要求交接码：请主人在操作台签发后再试。"
    # 没交接码就没凭据。本机私钥可以已经落盘（配对那一步自己生成的），
    # 但服务端发的东西一行都不许出现。
    text = _env_text()
    assert "KARMA_API_KEY=" not in text
    assert "KARMA_RUNTIME_KEY=" not in text


async def test_claim_writes_the_env_file_and_only_reports_fingerprints(monkeypatch):
    calls = _install(monkeypatch, [_request_payload(), _approved_payload()])
    started = await pt.karma_pairing_start("claw-001")
    out = await pt.karma_pairing_claim(handoff_code="K7P2-9RVX")

    assert calls[1]["path"] == "/v1/agent-pairing/claim"
    assert calls[1]["body"] == {"pairing_code": PAIRING_CODE, "handoff_code": "K7P2-9RVX"}

    assert out["ok"] is True
    assert out["status"] == "claimed"
    assert out["agent_id"] == "agent-1b4bb344ebfb"
    assert out["credentials"]["api_key"]["fingerprint"] == _fp(API_KEY)
    assert out["credentials"]["runtime_key"]["fingerprint"] == _fp(RUNTIME_KEY)
    assert out["env_file_mode"] == "0600"
    assert out["env_file_mode_enforced"] is (os.name == "posix")
    # 返回值里绝不能有明文。
    blob = json.dumps(out, ensure_ascii=False)
    assert API_KEY not in blob
    assert RUNTIME_KEY not in blob
    assert PAIRING_CODE not in blob
    assert started["user_code"]  # 申请那一步的结果还在手上

    path = pt.agent_env_path()
    text = path.read_text(encoding="utf-8")
    assert "KARMA_API_KEY=" + API_KEY in text
    assert "KARMA_RUNTIME_KEY=" + RUNTIME_KEY in text
    assert "KARMA_AGENT_ID=agent-1b4bb344ebfb" in text
    assert "Never paste this file into a chat" in text
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    # 服务端没说这把钥匙已经激活（回执里没有 runtime_key_binding.activated），
    # 那就还得让主人输匹配码 —— 这一步必须说清楚，不能让 agent 以为直接能用。
    assert "karma_runtime_bind_key" in out["next"]


async def test_claim_says_the_key_is_already_live_when_pairing_activated_it(monkeypatch):
    """配对即激活：回执说 activated，agent 就不该再让主人输匹配码。"""
    payload = _approved_payload()
    payload["runtime_key_binding"] = {
        "runtime_key_id": "c" * 32,
        "granted": True,
        "activated": True,
        "agent_fingerprint": "9f1c0f2b4d5e6a7b",
        "step_1": "nothing — already bound to the public key this pairing declared",
        "step_2": "",
        "step_3": "",
        "note": "this key is live",
    }
    _install(monkeypatch, [_request_payload(), payload])
    await pt.karma_pairing_start("claw-001")
    out = await pt.karma_pairing_claim()

    assert out["ok"] is True
    assert out["runtime_key_activated"] is True
    assert "配对即激活" in out["next"]
    assert "karma_runtime_bind_key" not in out["next"]
    # 私钥不会被这次写盘冲掉：agent 重新读得到自己的种子。
    assert "KARMA_AGENT_PRIVATE_KEY=" in _env_text()


async def test_claim_rejects_a_wrong_handoff_code(monkeypatch):
    calls = _install(monkeypatch, [
        _request_payload(),
        _http_error(403, "too many wrong handoff codes — pairing expired, start over"),
    ])
    await pt.karma_pairing_start("claw-001")
    out = await pt.karma_pairing_claim(handoff_code="ZZZZ-ZZZZ")

    assert calls[1]["body"]["handoff_code"] == "ZZZZ-ZZZZ"
    assert out["ok"] is False
    assert out["error"] == "handoff_rejected"
    text = _env_text()
    assert "KARMA_API_KEY=" not in text
    assert "KARMA_RUNTIME_KEY=" not in text


async def test_claim_reports_an_unknown_pairing(monkeypatch):
    _install(monkeypatch, [_http_error(404, "unknown pairing_code")])
    out = await pt.karma_pairing_claim(pairing_code="nope")
    assert out["ok"] is False
    assert out["error"] == "pairing_not_found"


async def test_claim_without_any_local_pairing_says_so(monkeypatch):
    calls = _install(monkeypatch, [])
    out = await pt.karma_pairing_claim()
    assert out["ok"] is False
    assert out["error"] == "pairing_code_missing"
    assert calls == []


async def test_claim_picks_the_pairing_code_up_from_the_local_state_file(monkeypatch):
    calls = _install(monkeypatch, [_request_payload(), _approved_payload()])
    await pt.karma_pairing_start("claw-001")
    out = await pt.karma_pairing_claim(handoff_code="K7P2-9RVX")
    assert calls[1]["body"]["pairing_code"] == PAIRING_CODE
    assert out["status"] == "claimed"


async def test_status_reports_the_step_without_credentials(monkeypatch):
    _install(monkeypatch, [
        _request_payload(),
        {"status": "awaiting_handoff", "handoff_state": "active",
         "handoff_expires_at": "2026-09-25T12:03:00Z", "poll_interval_seconds": 3},
    ])
    await pt.karma_pairing_start("claw-001")
    out = await pt.karma_pairing_status()
    assert out["ok"] is True
    assert out["status"] == "awaiting_handoff"
    assert out["handoff_state"] == "active"
    assert out["user_code"] == USER_CODE
    assert PAIRING_CODE not in json.dumps(out, ensure_ascii=False)
    assert "credentials" not in out


async def test_status_without_a_local_pairing_says_so(monkeypatch):
    _install(monkeypatch, [])
    out = await pt.karma_pairing_status()
    assert out["ok"] is False
    assert out["error"] == "no_local_pairing"


# --------------------------------------------------------------- 本机状态


async def test_local_status_reports_fingerprints_and_modes_only(monkeypatch):
    _install(monkeypatch, [_request_payload(), _approved_payload()])
    await pt.karma_pairing_start("claw-001")
    await pt.karma_pairing_claim(handoff_code="K7P2-9RVX")

    out = await pt.karma_pairing_local_status()
    assert out["ok"] is True
    assert out["env_file_present"] is True
    assert out["api_key_fingerprint"] == _fp(API_KEY)
    assert out["runtime_key_fingerprint"] == _fp(RUNTIME_KEY)
    assert out["agent_id"] == "agent-1b4bb344ebfb"
    assert out["pending_pairings"][0]["user_code"] == USER_CODE
    blob = json.dumps(out, ensure_ascii=False)
    assert API_KEY not in blob and RUNTIME_KEY not in blob and PAIRING_CODE not in blob


async def test_local_status_with_nothing_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("KARMA_AGENT_ENV_PATH", str(tmp_path / "nope" / "agent.env"))
    monkeypatch.setenv("KARMA_PAIRING_STATE_DIR", str(tmp_path / "nope-pairing"))
    out = await pt.karma_pairing_local_status()
    assert out["ok"] is True
    assert out["env_file_present"] is False
    assert out["pending_pairings"] == []


# --------------------------------------------------------------- 注册


def test_the_mcp_registers_the_pairing_tools():
    class _FakeMcp:
        def __init__(self) -> None:
            self.tools: list = []

        def add_tool(self, fn) -> None:
            self.tools.append(fn)

    mcp = _FakeMcp()
    pt.register_pairing_tools(mcp)
    assert [fn.__name__ for fn in mcp.tools] == [
        "karma_pairing_start",
        "karma_pairing_status",
        "karma_pairing_claim",
        "karma_pairing_local_status",
    ]
