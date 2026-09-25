# -*- coding: utf-8 -*-
"""Agent 侧自助配接：自己申请接入、自己把凭据落到本机。

为什么 agent 需要这两个工具：配对接入是**两把锁**（见 docs/AGENT_PAIRING_V1.md）。

* ``pairing_code`` —— agent 申请时拿到，证明「你就是当初发起的那一个进程」；
* ``handoff_code`` —— **主人在操作台点「签发交接码」才生成**，证明「主人真的把凭据
  交到了你手上」。

两把缺一个都领不走凭据。所以 agent 从来不需要、也绝不能让用户把密钥粘贴进聊天框：
它只要把 ``user_code`` 给主人，再把主人读给它的那串 8 位交接码填回 ``claim`` 即可。

明文凭据只写到本机（默认 ``~/.karma/agent.env``，0600），返回值里只有指纹。

环境变量：
  KARMA_RUNTIME_URL        Karma 节点地址（默认 http://localhost:8000）
  KARMA_AGENT_ENV_PATH     凭据落盘位置（默认 ~/.karma/agent.env）
  KARMA_PAIRING_STATE_DIR  配对状态目录（默认 ~/.karma/pairing）
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from karma_openclaw.http_client import api_post, runtime_base_url

#: 服务端 claim 的轮询间隔由它自己给（默认 3 秒），这里只是兜底。
DEFAULT_POLL_SECONDS = 3.0
#: 交接码 3 分钟有效（服务端 HANDOFF_TTL_SECONDS）—— 等主人读码的窗口别开太长。
DEFAULT_WAIT_SECONDS = 0.0
MAX_WAIT_SECONDS = 600.0


def pairing_state_dir() -> Path:
    override = os.environ.get("KARMA_PAIRING_STATE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".karma" / "pairing"


def agent_env_path() -> Path:
    override = os.environ.get("KARMA_AGENT_ENV_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".karma" / "agent.env"


def fingerprint(secret: str | None) -> str:
    """只回指纹，不回明文 —— 聊天记录里出现它也没用。"""
    text = (secret or "").strip()
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return "sha256:" + digest[:16]


def _harden(path: Path, mode: int) -> None:
    """尽力把权限收紧；Windows 上 chmod 只影响只读位，不影响主流程。"""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _mkdir_secure(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _harden(path, 0o700)


def _write_secret(path: Path, text: str, mode: int = 0o600) -> None:
    """先写临时文件再原子替换 —— 别让别的进程读到半个文件。"""
    _mkdir_secure(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    _harden(tmp, mode)
    os.replace(tmp, path)
    _harden(path, mode)


def _file_mode(path: Path) -> str:
    try:
        return "0%o" % stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return ""


def _server_detail(exc: Exception) -> str:
    resp = getattr(exc, "response", None)
    if resp is None:
        return str(exc)
    try:
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("detail"):
            return str(payload["detail"])
    except Exception:  # noqa: BLE001
        pass
    return (getattr(resp, "text", "") or str(exc))[:300]


def _missing_user_code() -> dict[str, Any]:
    return {
        "ok": False,
        "error": "user_code_required",
        "hint": "Pass the user_code from karma_pairing_start (or the one on screen).",
    }


def _state_files() -> list[Path]:
    directory = pairing_state_dir()
    if not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.glob("*.json") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _save_pairing(payload: dict[str, Any]) -> Path:
    user_code = str(payload.get("user_code") or "")
    stem = user_code.replace("/", "_").replace("\\", "_") or "pairing"
    path = pairing_state_dir() / (stem + ".json")
    record = {
        "user_code": user_code,
        "pairing_code": payload.get("pairing_code"),
        "verification_uri": payload.get("verification_uri"),
        "expires_at": payload.get("expires_at"),
        "poll_interval_seconds": payload.get("poll_interval_seconds"),
        "claim_endpoint": payload.get("claim_endpoint"),
        "saved_at": int(time.time()),
    }
    _write_secret(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return path


def _load_pairing(user_code: str = "") -> dict[str, Any] | None:
    wanted = (user_code or "").strip().upper()
    for path in _state_files():
        if wanted and path.stem.upper() != wanted:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict) and data.get("pairing_code"):
            return data
    return None


def _resolve_pairing_code(pairing_code: str = "", user_code: str = "") -> tuple[str, dict[str, Any] | None]:
    """显式给了就用；没给就从本机状态目录里挑最近的一次（重启也能接着领）。"""
    explicit = (pairing_code or "").strip()
    if explicit:
        return explicit, None
    found = _load_pairing(user_code)
    if found is None:
        return "", None
    return str(found.get("pairing_code") or ""), found


async def _claim_once(pairing_code: str, handoff_code: str = "") -> dict[str, Any]:
    body: dict[str, Any] = {"pairing_code": pairing_code}
    code = (handoff_code or "").strip()
    if code:
        body["handoff_code"] = code
    return await api_post("/v1/agent-pairing/claim", body)


async def karma_pairing_start(
    agent_name: str,
    platform: str = "openclaw",
    requested_side: str = "",
    requested_vertical: str = "",
    self_description: str = "",
    endpoint_url: str = "",
    public_key: str = "",
) -> dict[str, Any]:
    """申请接入 Karma。把返回的 user_code / verification_uri 交给主人。

    这一步不花任何钱、也不产生任何权限：它只是让主人在操作台里看到「谁在申请」。
    主人批准并点「签发交接码」之后，agent 再调 karma_pairing_claim 领凭据。

    ``pairing_code`` 不在这里回显 —— 它只落盘在本机 0600 的状态文件里。
    """
    name = (agent_name or "").strip()
    if not name:
        return {
            "ok": False,
            "error": "agent_name_required",
            "hint": "Give this agent a name your owner will recognise (e.g. claw-001).",
        }
    body: dict[str, Any] = {"agent_name": name, "platform": (platform or "openclaw").strip()}
    for key, value in (
        ("requested_side", requested_side),
        ("requested_vertical", requested_vertical),
        ("self_description", self_description),
        ("endpoint_url", endpoint_url),
        ("public_key", public_key),
    ):
        if (value or "").strip():
            body[key] = value.strip()
    try:
        payload = await api_post("/v1/agent-pairing/request", body)
    except Exception as exc:  # noqa: BLE001 — 把服务端原话带回去
        return {"ok": False, "error": "pairing_request_failed", "detail": _server_detail(exc)}
    if not isinstance(payload, dict) or not payload.get("pairing_code"):
        return {"ok": False, "error": "pairing_request_unexpected", "detail": str(payload)[:300]}

    path = _save_pairing(payload)
    user_code = str(payload.get("user_code") or "")
    uri = str(payload.get("verification_uri") or "")
    return {
        "ok": True,
        "status": "pending_owner",
        "user_code": user_code,
        "verification_uri": uri,
        "expires_at": payload.get("expires_at"),
        "poll_interval_seconds": payload.get("poll_interval_seconds") or DEFAULT_POLL_SECONDS,
        "pairing_state_file": str(path),
        "hand_to_owner": (
            "把这一行交给主人：" + (uri or user_code) + " —— 他在 Karma 操作台里"
            "输入 " + user_code + " 就能看到是谁在申请接入。"
        ),
        "owner_steps": [
            "打开 Karma 操作台 → Agent 接入 → 配对接入",
            "输入 " + user_code + " → 核对 agent 名称/公钥指纹 → 点「批准」并划额度",
            "点「签发交接码」，把屏幕上那串 8 位码读给我（3 分钟内有效）",
        ],
        "next": (
            "主人批准并签发交接码后，调 karma_pairing_claim(handoff_code=\"<他念给你的那串>\")。"
        ),
        "note": "pairing_code 只写在本机 " + str(path) + "，聊天里不出现。",
    }


async def karma_pairing_status(user_code: str = "") -> dict[str, Any]:
    """这次配对接进到哪一步了（等批准 / 等交接码 / 已交付 / 作废）。

    读的是本机状态文件 + 服务端 claim 的结论；不会输出任何凭据。
    """
    pairing_code, record = _resolve_pairing_code("", user_code)
    if not pairing_code:
        return {
            "ok": False,
            "error": "no_local_pairing",
            "hint": "Call karma_pairing_start first, or pass pairing_code explicitly.",
        }
    try:
        payload = await _claim_once(pairing_code)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "pairing_status_failed", "detail": _server_detail(exc)}
    out: dict[str, Any] = {
        "ok": True,
        "status": payload.get("status"),
        "user_code": (record or {}).get("user_code") or user_code,
        "handoff_state": payload.get("handoff_state"),
        "handoff_expires_at": payload.get("handoff_expires_at"),
        "expires_at": payload.get("expires_at"),
        "poll_interval_seconds": payload.get("poll_interval_seconds") or DEFAULT_POLL_SECONDS,
    }
    if payload.get("status") == "awaiting_handoff":
        out["ask_owner"] = (
            "交接码过期了，请主人在操作台点「重新签发」。"
            if payload.get("handoff_state") == "expired"
            else "主人在操作台点「签发交接码」之后，把那串 8 位码念给我。"
        )
    return out


def _env_file_text(agent_id: str, base_url: str, env: dict[str, str]) -> str:
    lines = [
        "# Karma agent credentials — written by karma_pairing_claim (mode 0600).",
        "# Never paste this file into a chat, an issue, or a shared log.",
        "KARMA_AGENT_ID=" + agent_id,
        "KARMA_RUNTIME_URL=" + base_url,
    ]
    for key in ("KARMA_API_KEY", "KARMA_RUNTIME_KEY"):
        value = str(env.get(key) or "").strip()
        if value:
            lines.append(key + "=" + value)
    return "\n".join(lines) + "\n"


async def karma_pairing_claim(
    handoff_code: str = "",
    pairing_code: str = "",
    user_code: str = "",
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
) -> dict[str, Any]:
    """领凭据：``pairing_code``（本机）+ ``handoff_code``（主人念给你的那串）。

    拿到之后**只写盘、不回显**：默认写到 ``~/.karma/agent.env``（0600），返回值里
    只有 ``sha256:…`` 指纹和文件路径。所以这一步可以放心地出现在聊天记录里。

    ``handoff_code`` 还没拿到时先调一次（不传码），返回 ``awaiting_handoff`` ——
    那就去问主人要那串码，拿到再调一次。
    """
    resolved, record = _resolve_pairing_code(pairing_code, user_code)
    if not resolved:
        return {
            "ok": False,
            "error": "pairing_code_missing",
            "hint": (
                "Call karma_pairing_start first, or pass the pairing_code it saved "
                "at ~/.karma/pairing/<user_code>.json"
            ),
        }

    deadline = time.monotonic() + min(max(0.0, float(wait_seconds or 0.0)), MAX_WAIT_SECONDS)
    payload: dict[str, Any] = {}
    while True:
        try:
            payload = await _claim_once(resolved, handoff_code)
        except Exception as exc:  # noqa: BLE001
            detail = _server_detail(exc)
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code == 403 and "handoff" in detail:
                return {
                    "ok": False,
                    "error": "handoff_rejected",
                    "status": "rejected",
                    "detail": detail,
                    "hint": (
                        "The handoff code does not match (or was guessed too many times — "
                        "then the pairing is dead and the owner must approve a fresh request). "
                        "Ask the owner to read the code straight off the Console again."
                    ),
                }
            if status_code == 404:
                return {
                    "ok": False,
                    "error": "pairing_not_found",
                    "detail": detail,
                    "hint": "This pairing_code is unknown; start a new pairing request.",
                }
            return {"ok": False, "error": "claim_failed", "detail": detail}

        status = str(payload.get("status") or "")
        if status in {"pending", "awaiting_handoff"} and time.monotonic() < deadline:
            interval = float(payload.get("poll_interval_seconds") or DEFAULT_POLL_SECONDS)
            await asyncio.sleep(max(0.5, interval))
            continue
        break

    status = str(payload.get("status") or "")
    if status in {"pending", "awaiting_handoff"}:
        state = payload.get("handoff_state")
        out = {
            "ok": False,
            "status": status,
            "handoff_state": state,
            "handoff_expires_at": payload.get("handoff_expires_at"),
            "user_code": (record or {}).get("user_code") or user_code,
            "expires_at": payload.get("expires_at"),
            "poll_interval_seconds": payload.get("poll_interval_seconds") or DEFAULT_POLL_SECONDS,
        }
        if status == "pending":
            out["ask_owner"] = (
                "主人还没批准。把 karma_pairing_start 给的链接/短码再发他一次。"
            )
        elif state == "expired":
            out["ask_owner"] = "交接码过期了，请主人在操作台点「重新签发」。"
        elif state == "none":
            out["ask_owner"] = "请主人在操作台点「签发交接码」，再把那串 8 位码念给我。"
        else:
            out["ask_owner"] = "请主人把操作台上的交接码念给我。"
        return out

    if status != "approved":
        return {
            "ok": False,
            "status": status or "unknown",
            "error": "nothing_to_deliver",
            "hint": "This pairing has nothing left to deliver; start a new one if needed.",
        }

    credentials = dict(payload.get("credentials") or {})
    env = dict(payload.get("env_snippet") or {})
    agent_id = str(payload.get("agent_id") or env.get("KARMA_AGENT_ID") or "")
    base_url = str(env.get("KARMA_RUNTIME_URL") or runtime_base_url())
    api_key = str(credentials.get("api_key") or "")
    runtime_key = str(credentials.get("runtime_key") or "")
    if not api_key and not runtime_key:
        return {
            "ok": False,
            "error": "empty_credentials",
            "hint": "The server returned approved but no credential; retry the pairing.",
        }

    path = agent_env_path()
    _write_secret(path, _env_file_text(agent_id, base_url, env))

    delivered: dict[str, Any] = {"api_key": {"present": bool(api_key), "fingerprint": fingerprint(api_key)}}
    if runtime_key:
        delivered["runtime_key"] = {
            "present": True,
            "fingerprint": fingerprint(runtime_key),
            "runtime_key_id": credentials.get("runtime_key_id"),
        }
    out = {
        "ok": True,
        "status": "claimed",
        "agent_id": agent_id,
        "owner_identity_id": payload.get("owner_identity_id"),
        "env_path": str(path),
        # 目标是 0600；Windows 没有 POSIX 权限位（走 ACL），所以把「是否真落地」也报出来，
        # 免得把 0666 说成 0600。
        "env_file_mode": "0600",
        "env_file_mode_enforced": os.name == "posix",
        "env_file_actual_mode": _file_mode(path),
        "credentials": delivered,
        "handoff": payload.get("handoff") or {"required": True, "consumed": True},
        "note": (
            "凭据已写入本机 " + str(path) + "（0600），聊天里不出现明文。"
            "丢失就要重新配对：服务端已经不再保留它。"
        ),
    }
    if not out["env_file_mode_enforced"]:
        out["env_file_mode_note"] = (
            "Windows 用 ACL 而不是 POSIX 权限位；这个文件在你的用户目录下，"
            "只要不共享、不提交进仓库就没人读得到。"
        )
    if runtime_key:
        out["next"] = (
            "下一步是接入确认：调 karma_runtime_bind_key 拿一串 8 位匹配码交给主人，"
            "他在操作台输入并签名后这把钥匙才生效（在那之前一分钱都动不了）。"
        )
    return out


async def karma_pairing_local_status() -> dict[str, Any]:
    """本机现在握着什么：待领取的配对 + 已落盘的凭据（只报指纹和权限位）。"""
    pending = []
    for path in _state_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        pending.append(
            {
                "user_code": data.get("user_code"),
                "verification_uri": data.get("verification_uri"),
                "expires_at": data.get("expires_at"),
                "state_file": str(path),
                "state_file_mode": _file_mode(path),
            }
        )

    path = agent_env_path()
    env: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()

    return {
        "ok": True,
        "env_path": str(path),
        "env_file_present": path.is_file(),
        "env_file_mode": _file_mode(path) if path.is_file() else "",
        "agent_id": env.get("KARMA_AGENT_ID", ""),
        "runtime_url": env.get("KARMA_RUNTIME_URL", ""),
        "api_key_fingerprint": fingerprint(env.get("KARMA_API_KEY")),
        "runtime_key_fingerprint": fingerprint(env.get("KARMA_RUNTIME_KEY")),
        "pending_pairings": pending,
        "note": "只报指纹：明文凭据永远只在本机那份 0600 文件里。",
    }


def register_pairing_tools(mcp: FastMCP) -> None:
    """把自助接入工具挂进 MCP（函数体在模块级，单测可以直接调）。"""
    mcp.add_tool(karma_pairing_start)
    mcp.add_tool(karma_pairing_status)
    mcp.add_tool(karma_pairing_claim)
    mcp.add_tool(karma_pairing_local_status)
