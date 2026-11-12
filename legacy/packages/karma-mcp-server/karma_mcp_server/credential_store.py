"""凭据**写入**（配对流程专用）。

与 ``credentials.py``（只读）分开：读的路径要尽可能简单、无副作用；写的路径只有
``karma_connect_claim`` 会走，并且必须 0600 + 原子落盘。

凭据文件**永不回显** —— 返回给调用方的只有指纹。
"""

from __future__ import annotations

import os
from pathlib import Path

from karma_mcp_server.credentials import agent_env_path


def state_dir() -> Path:
    """配对状态目录（含 pairing_code，属于秘密）。"""
    override = os.environ.get("KARMA_MCP_STATE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".karma" / "pairings"


def _write_secret(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def upsert_credential(name: str, value: str) -> Path:
    """把一对键值并进凭据文件（0600），同名行就地替换。"""
    path = agent_env_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    prefix = name + "="
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().startswith(prefix):
            if not replaced:
                out.append(prefix + value)
                replaced = True
            continue
        out.append(line)
    if not replaced:
        out.append(prefix + value)
    _write_secret(path, "\n".join(out).rstrip("\n") + "\n")
    return path


def write_env_file(text: str) -> Path:
    """整份重写凭据文件（领取凭据时用）。"""
    path = agent_env_path()
    _write_secret(path, text)
    return path


def write_pairing_state(user_code: str, payload_json: str) -> Path:
    """配对状态（含 pairing_code）落到本机 0600 文件，聊天里不出现。"""
    safe = "".join(ch for ch in (user_code or "pairing") if ch.isalnum() or ch in "-_") or "pairing"
    path = state_dir() / (safe.upper() + ".json")
    _write_secret(path, payload_json)
    return path
