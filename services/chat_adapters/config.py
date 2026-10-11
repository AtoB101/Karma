"""适配器配置 —— 全部来自环境变量。

红线：这里只读「平台凭据」（webhook 密钥、发送 token），**绝不**读私钥、助记词
或任何 Karma 资金密钥。适配器不是 agent，也不是钱包；它连不到钱。
"""
from __future__ import annotations

import os

#: 聊天里从不回显任何地址以外的信息；接入链接指向操作台（主人已认证的会话）。
DEFAULT_CONSOLE_BASE_URL = "https://karma-network.ai"


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def env_name() -> str:
    """运行环境名。dev/test/local 下**不发**真实出站消息（除非显式打开）。"""
    return (_env("KARMA_ENV") or _env("ENV") or "dev").lower()


def console_base_url() -> str:
    return (_env("KARMA_CONSOLE_BASE_URL") or DEFAULT_CONSOLE_BASE_URL).rstrip("/")


def console_pairing_url() -> str:
    """主人在操作台批准配对的那一页。聊天里只发链接，绝不发凭据。"""
    override = _env("KARMA_CONSOLE_PAIRING_URL")
    if override:
        return override
    return f"{console_base_url()}/?view=pairing"


def console_agents_url() -> str:
    """操作台里「我的助理 agent」那一页。"""
    return f"{console_base_url()}/?view=agents"


def notify_token() -> str:
    """``POST /v1/adapters/notify`` 的静态 bearer。没配 = 这条通道不存在。"""
    return _env("KARMA_ADAPTER_NOTIFY_TOKEN")