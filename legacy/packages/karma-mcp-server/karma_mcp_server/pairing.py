"""配对状态 —— 只落本机，不落聊天。

``pairing_code`` 是能领凭据的东西，等同于半个密码，所以它**只**写在本机 0600 文件里，
任何工具返回值里都不出现。
"""

from __future__ import annotations

import json
from typing import Any

from karma_mcp_server.credential_store import state_dir, write_pairing_state


def _state_files() -> list:
    directory = state_dir()
    try:
        return sorted(
            (p for p in directory.glob("*.json") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []


def save_pairing(payload: dict[str, Any]) -> Any:
    return write_pairing_state(
        str(payload.get("user_code") or ""),
        json.dumps(payload, ensure_ascii=False, indent=2) + chr(10),
    )


def load_pairing(user_code: str = "") -> dict[str, Any] | None:
    wanted = (user_code or "").strip().upper()
    for path in _state_files():
        if wanted and path.stem.upper() != wanted:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001, S112 - 坏的状态文件直接跳过，不把链绑在一个读不动的文件上
            continue
        if isinstance(data, dict) and data.get("pairing_code"):
            return data
    return None


def resolve_pairing_code(
    pairing_code: str = "", user_code: str = ""
) -> tuple[str, dict[str, Any] | None]:
    """显式给了就用；没给就从本机状态目录里挑最近的一次。"""
    explicit = (pairing_code or "").strip()
    if explicit:
        return explicit, None
    found = load_pairing(user_code)
    if found is None:
        return "", None
    return str(found.get("pairing_code") or ""), found


def credentials_env_text(agent_id: str, base_url: str, env: dict[str, str]) -> str:
    """写进 ~/.karma/agent.env 的正文（0600）。"""
    lines = [
        "# Karma agent credentials - written by karma_connect_claim (mode 0600).",
        "# Never paste this file into a chat, an issue, or a shared log.",
        "KARMA_AGENT_ID=" + agent_id,
        "KARMA_RUNTIME_URL=" + base_url,
    ]
    for key in ("KARMA_API_KEY", "KARMA_RUNTIME_KEY"):
        value = str(env.get(key) or "").strip()
        if value:
            lines.append(key + "=" + value)
    return chr(10).join(lines) + chr(10)
