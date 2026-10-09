"""凭据读取 —— **只读**，绝不回显。

解析顺序：环境变量（宿主显式注入的优先） > ``~/.karma/agent.env``（0600）。

本模块**不写盘**。写入凭据属于配对流程（``karma_connect``），由后续 S3 负责。
"""

from __future__ import annotations

import os
from pathlib import Path

#: 本包会读的键。注意：这里**没有**任何私钥/助记词键。
CREDENTIAL_KEYS = (
    "KARMA_RUNTIME_KEY",
    "KARMA_API_KEY",
    "KARMA_RUNTIME_URL",
    "KARMA_AGENT_ID",
    "KARMA_AGENT_PRIVATE_KEY",
)

#: 明确禁止出现在本进程环境里的键（架构 §4 / 安全 R1）。
FORBIDDEN_ENV_KEYS = (
    "KARMA_PRIVATE_KEY",
    "USER_PRIVATE_KEY",
    "DEPLOYER_PRIVATE_KEY",
    "KARMA_MNEMONIC",
    "MNEMONIC",
)


def agent_env_path() -> Path:
    override = os.environ.get("KARMA_AGENT_ENV_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".karma" / "agent.env"


def read_agent_env() -> dict[str, str]:
    """解析凭据文件；读不动就返回空 dict（不抛）。"""
    try:
        text = agent_env_path().read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = value.strip()
    return values


def credential(
    name: str,
    *,
    env: dict[str, str] | None = None,
    file_values: dict[str, str] | None = None,
) -> str:
    """环境变量优先，否则回落凭据文件。"""
    source = os.environ if env is None else env
    value = (source.get(name) or "").strip()
    if value:
        return value
    values = read_agent_env() if file_values is None else file_values
    return str(values.get(name) or "").strip()


def check_forbidden_env(env: dict[str, str] | None = None) -> list[str]:
    """返回环境里**不该有**的私钥类键名（只返回键名，绝不返回值）。

    这是安全红线 R1 的可执行检查：启动时若发现私钥被注入 MCP 进程，直接拒绝启动。
    """
    source = os.environ if env is None else env
    return [key for key in FORBIDDEN_ENV_KEYS if (source.get(key) or "").strip()]
