# -*- coding: utf-8 -*-
"""凭据落在哪、以及怎么把它读回来。

`karma_pairing_claim` 把凭据写到 ``~/.karma/agent.env``（0600）。但在此之前没有任何
代码会把它读回 ``os.environ`` —— 也就是说：**已经跑着的 MCP 进程永远看不到刚领到的
凭据**，非要宿主把 MCP server 重启一次才生效。而「宿主重启」恰恰是我们不能假设用户
做得到的那一步（OpenClaw 的 config 重载链路本身就可能坏着）。

所以路径解析放在这一个模块里，写盘和读盘共用；HTTP 层每次要用凭据时按文件
mtime+size 判断是否需要重读，文件变了就立刻生效。
"""
from __future__ import annotations

import os
from pathlib import Path

#: 这两把钥匙在 agent 侧的用途不同：API key 调公共 API，Runtime key 调 /runtime/*。
CREDENTIAL_KEYS = (
    "KARMA_API_KEY",
    "KARMA_RUNTIME_KEY",
    "KARMA_RUNTIME_URL",
    "KARMA_AGENT_ID",
    "KARMA_AGENT_PRIVATE_KEY",
)


def agent_env_path() -> Path:
    """凭据文件位置：``KARMA_AGENT_ENV_PATH`` 覆盖，否则 ``~/.karma/agent.env``。"""
    override = os.environ.get("KARMA_AGENT_ENV_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".karma" / "agent.env"


def read_agent_env() -> dict:
    """把文件解析成 dict；文件不存在或读不动时返回空 dict（不抛）。"""
    path = agent_env_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = value.strip()
    return values


_cache: dict = {"stamp": None, "values": {}}


def _stamp():
    path = agent_env_path()
    try:
        st = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), st.st_mtime_ns, st.st_size)


def load_agent_env(force: bool = False) -> dict:
    """磁盘上的凭据；文件变了就重读，没变就吃缓存（每次工具调用都会走这里）。"""
    stamp = _stamp()
    if force or _cache["stamp"] != stamp:
        _cache["stamp"] = stamp
        _cache["values"] = read_agent_env()
    return _cache["values"]


def invalidate_agent_env() -> None:
    """刚写完文件时调用，避免同一进程里还吃旧缓存。"""
    _cache["stamp"] = None
    load_agent_env(force=True)


def upsert_credential(name: str, value: str) -> Path:
    """把一对键值并进凭据文件（0600），同名行就地替换。

    agent 自己的 Ed25519 私钥要先落盘再上报：进程崩了、宿主重启了，它还得在。
    """
    path = agent_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    prefix = name + "="
    out: list = []
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
    text = "\n".join(out).rstrip("\n") + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    invalidate_agent_env()
    return path


def credential(name: str) -> str:
    """环境变量优先（宿主显式注入的压过文件），否则回落到凭据文件。"""
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    return str(load_agent_env().get(name) or "").strip()
