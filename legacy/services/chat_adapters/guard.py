"""出站文本的凭据卫生 —— 聊天窗口是最容易泄漏的地方。

任何要发进聊天窗口的文本都必须先过 ``assert_no_secret()``：一旦发现像 Runtime Key
/ 私钥 / 原始签名的东西，宁可**不发**（抛错让调用方失败），也不发出去。

为什么单列一个模块：这是「适配器永远不碰密钥」这条红线在**出站方向**上的守门人
（入站方向由 webhook 验签守）。少了它，一次手滑的 f-string 就能把钥匙贴进群聊。
"""
from __future__ import annotations

import re

#: 出站文本长度上限（Telegram 4096 / WhatsApp 4096，取小者再留一点余量）。
MAX_OUTBOUND_CHARS = 4000

#: 控制字符（保留 \t \n；\r 会在归一化阶段转成 \n）。
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: 疑似凭据的形态。命中即**拒发**。
#:
#: 刻意**不**拦 ``0x`` + 64 位十六进制：那是交易哈希与证据哈希，本来就是公开的，
#: 拦掉会把正常回执也一起拦死。真正的私钥是 32 字节（同样是 64 hex），所以私钥
#: 只靠这一条不够 —— 它由下面的「环境变量赋值形态」和「65 字节签名」两条兜底。
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Runtime Key 明文
    re.compile(r"KRM_RT_[A-Za-z0-9_\-]{6,}"),
    # PEM 私钥
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    # .env 形态：KARMA_RUNTIME_KEY=... / AGENT_PRIVATE_KEY=... / PRIVATE_KEY=...
    re.compile(r"(?i)\b(?:KARMA_)?(?:AGENT_|DEPLOYER_|USER_)?PRIVATE_KEY\s*[:=]"),
    re.compile(r"(?i)\bKARMA_RUNTIME_KEY\s*[:=]"),
    # 原始签名（65 字节 r||s||v → 0x + 130 hex）
    re.compile(r"\b0x[0-9a-fA-F]{130}\b"),
)


class SecretLeakError(RuntimeError):
    """出站文本里扫到了疑似凭据 —— 拒发。"""


def find_secret(text: str) -> str | None:
    """返回命中的模式（用于日志与用例断言），没命中返回 ``None``。"""
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return pattern.pattern
    return None


def assert_no_secret(text: str) -> str:
    """出站前的最后一道闸：命中疑似凭据就抛错，绝不把它发进聊天窗口。"""
    hit = find_secret(text)
    if hit:
        raise SecretLeakError("outbound text looks like it carries a credential; refusing to send")
    return text


def sanitize_text(text: object, *, limit: int = MAX_OUTBOUND_CHARS) -> str:
    """归一化一段要发出去 / 记下来的文本：去控制字符、压空行、截断。"""
    raw = str(text if text is not None else "")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = _CONTROL_CHARS.sub("", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    raw = raw.strip()
    if len(raw) > limit:
        raw = raw[:limit]
    return raw


def mask_chat_id(chat_id: object) -> str:
    """日志里只留会话号后 4 位 —— 会话号本身不是凭据，但也没必要全量进日志。"""
    tail = str(chat_id or "")[-4:]
    return f"***{tail}" if tail else "***"