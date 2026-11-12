"""Runtime Key 接入工具 —— 让 agent 自己把公钥钉上去、自己等主人输匹配码。

为什么必须有这一步：Runtime Key 是不记名令牌（KRM_RT_… 谁拿着谁能花主人的钱）。
所以这把钥匙在铸出来的时候就必须指名一个 agent，agent 申请接入后拿到 8 位匹配码，
主人在 Karma 操作台手输这串码并签名确认，绑定才生效 —— 在那之前这把钥匙一分钱都
动不了（服务端一律 403）。偷到 key 的人手上没有主人屏幕上的那串码，所以接不进去。

环境变量：
  KARMA_RUNTIME_KEY        KRM_RT_…
  KARMA_AGENT_ID           操作台里这把钥匙指名的 agent id
  KARMA_AGENT_PRIVATE_KEY  Ed25519 私钥（base64 32 字节 或 64 位 hex）—— 只在本机
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from karma_openclaw.agent_binding import (
    agent_id_from_env,
    agent_key_from_env,
    agent_public_key_b64,
)
from karma_openclaw.http_client import (
    refresh_signing_mode,
    runtime_get,
    runtime_key,
    runtime_post,
)

# 匹配码 3 分钟过期（服务端 BIND_CODE_TTL_SECONDS）；轮询间隔取 5 秒。
POLL_INTERVAL_SECONDS = 5.0


def _missing_runtime_key() -> dict[str, Any]:
    return {
        "ok": False,
        "error": "runtime_key_missing",
        "hint": "Set KARMA_RUNTIME_KEY (KRM_RT_…) for this Claw process",
    }


def _missing_agent_key() -> dict[str, Any]:
    return {
        "ok": False,
        "error": "agent_private_key_missing",
        "hint": (
            "Set KARMA_AGENT_PRIVATE_KEY (base64 of 32 raw bytes, or 64-char hex). "
            "It never leaves this process; Karma only ever stores the public key."
        ),
    }


def _display_code(value: str) -> str:
    """XXXX-XXXX —— 服务端已经是这个形式，这里只是兜底收敛。"""
    text = (value or "").strip().upper()
    if len(text) == 8:
        return f"{text[:4]}-{text[4:]}"
    return text


async def karma_runtime_bind_key(agent_id: str = "") -> dict[str, Any]:
    """POST /runtime/bind-key — 把本机 agent 的 Ed25519 公钥钉在这把 Runtime Key 上。

    返回 status=pending_activation 时绑定还没生效：把 activation_code（8 位匹配码）
    交给这把钥匙的主人，让他在 Karma 操作台「接入确认」里输入并签名。确认之前任何
    动作端都是 403；确认之后本进程会自动改成带签名调用（也可以调
    karma_runtime_await_activation 等它生效）。
    """
    if not runtime_key():
        return _missing_runtime_key()
    key = agent_key_from_env()
    if key is None:
        return _missing_agent_key()
    try:
        target = (agent_id or "").strip() or agent_id_from_env()
        if not target:
            info = await runtime_get("/runtime/permissions")
            target = str((info or {}).get("agent_binding") or "").strip()
        if not target:
            return {
                "ok": False,
                "error": "agent_id_required",
                "hint": "Pass agent_id=… or set KARMA_AGENT_ID to the agent this key names",
            }
        payload = {
            "agent_id": target,
            "agent_public_key": agent_public_key_b64(key),
            "client_nonce": uuid.uuid4().hex,
        }
        out = await runtime_post("/runtime/bind-key", payload)
    except Exception as exc:  # noqa: BLE001 — MCP 工具要把服务端原话带回去
        return {"ok": False, "error": "bind_key_failed", "detail": str(exc)}
    status = str((out or {}).get("status") or "")
    if status == "active":
        await refresh_signing_mode()
        return {
            "ok": True,
            "status": "active",
            "agent_id": (out or {}).get("agent_id") or target,
            "signed_requests": True,
            "detail": "already bound to the same public key; signing is on",
        }
    code = _display_code(str((out or {}).get("activation_code") or ""))
    return {
        "ok": True,
        "status": status or "pending_activation",
        "agent_id": (out or {}).get("agent_id") or target,
        "activation_code": code,
        "activation_expires_at": (out or {}).get("activation_expires_at"),
        "activation_attempts_left": (out or {}).get("activation_attempts_left"),
        "hand_to_owner": (
            "把这串匹配码交给钥匙的主人：" + code + " —— 他在 Karma 操作台"
            "「接入确认」里输入并签名后，这次接入才生效（3 分钟内有效）。"
        ),
        "owner_steps": [
            "打开 Karma 操作台 → AI Agent 钥匙卡片 → 接入确认",
            "输入这串 8 位匹配码，用钱包签名确认",
        ],
        "pending_binding": (out or {}).get("pending_binding"),
    }


async def karma_runtime_binding_status() -> dict[str, Any]:
    """GET /runtime/permissions — 这把钥匙现在到哪一步了（未激活 / 待输码 / 已生效）。"""
    if not runtime_key():
        return _missing_runtime_key()
    try:
        signed = await refresh_signing_mode()
        info = await runtime_get("/runtime/permissions")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "runtime_call_failed", "detail": str(exc)}
    return {
        "ok": True,
        "signed_requests": signed,
        "key_binding": (info or {}).get("key_binding"),
        "agent_binding": (info or {}).get("agent_binding"),
        "agent_fingerprint": (info or {}).get("agent_fingerprint"),
        "activation_required": (info or {}).get("activation_required"),
        "activation_code_ttl_seconds": (info or {}).get("activation_code_ttl_seconds"),
        "pending_binding": (info or {}).get("pending_binding"),
        "permissions": (info or {}).get("permissions"),
        "single_limit": (info or {}).get("single_limit"),
        "daily_limit": (info or {}).get("daily_limit"),
        "expire_time": (info or {}).get("expire_time"),
    }


async def karma_runtime_await_activation(timeout_seconds: float = 180.0) -> dict[str, Any]:
    """等主人在操作台输入匹配码。生效后本进程自动改成带签名调用。

    超时返回 ok=False + status=pending（匹配码 3 分钟过期）。过期不用重铸钥匙：
    重新调 karma_runtime_bind_key 拿一串新码，再交给主人即可。
    """
    if not runtime_key():
        return _missing_runtime_key()
    deadline = time.monotonic() + max(0.0, float(timeout_seconds or 0.0))
    while True:
        try:
            active = await refresh_signing_mode()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "runtime_call_failed", "detail": str(exc)}
        if active:
            info = await runtime_get("/runtime/permissions")
            return {
                "ok": True,
                "status": "active",
                "key_binding": (info or {}).get("key_binding"),
                "agent_binding": (info or {}).get("agent_binding"),
                "permissions": (info or {}).get("permissions"),
            }
        if time.monotonic() >= deadline:
            return {
                "ok": False,
                "status": "pending",
                "error": "activation_timeout",
                "hint": (
                    "owner has not entered the matching code yet; call "
                    "karma_runtime_bind_key again for a fresh code"
                ),
            }
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def register_runtime_tools(mcp: FastMCP) -> None:
    """把接入工具挂进 MCP（函数体在模块级，单测可以直接调）。"""
    mcp.add_tool(karma_runtime_bind_key)
    mcp.add_tool(karma_runtime_binding_status)
    mcp.add_tool(karma_runtime_await_activation)
