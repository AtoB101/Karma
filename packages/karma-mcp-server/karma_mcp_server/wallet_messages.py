"""钱包待签文案 —— 与 ``services/runtime_wallet.py`` **逐字对齐**。

用户签的就是这几行。MCP 只负责把它原样显示给用户，**绝不代签**。
改动任何一行都会让后端验签失败，因此这里由测试钉死。
"""

from __future__ import annotations

from datetime import datetime

_NEWLINE = chr(10)

#: 最长可接受的钱包签名文案长度（防注入式超长文本）。
MAX_MESSAGE_CHARS = 4000


def build_create_key_message(
    *,
    karma_identity_id: str,
    wallet_address: str,
    permissions: list[str],
    single_limit: float,
    daily_limit: float,
    expire_time: datetime | str | None,
    agent_name: str,
    agent_binding: str | None,
) -> str:
    """铸造 Runtime Key 时主人签的那段文字（含额度与边界）。"""
    if expire_time is None or (isinstance(expire_time, str) and not expire_time.strip()):
        expire_line = "never"
    elif isinstance(expire_time, str):
        expire_line = expire_time.strip()
    else:
        expire_line = expire_time.isoformat()
    lines = [
        "Karma Runtime Key Create",
        "karma_identity_id:" + karma_identity_id,
        "wallet_address:" + wallet_address,
        "permissions:" + ",".join(sorted(permissions)),
        "single_limit:" + str(single_limit),
        "daily_limit:" + str(daily_limit),
        "expire_time:" + expire_line,
        "agent_name:" + agent_name,
        "agent_binding:" + (agent_binding or ""),
    ]
    return _NEWLINE.join(lines)


def build_revoke_key_message(*, key_id: str, karma_identity_id: str, wallet_address: str) -> str:
    """停用 Runtime Key 时主人签的那段文字。"""
    return _NEWLINE.join(
        [
            "Karma Runtime Key Revoke",
            "key_id:" + key_id,
            "karma_identity_id:" + karma_identity_id,
            "wallet_address:" + wallet_address,
        ]
    )
