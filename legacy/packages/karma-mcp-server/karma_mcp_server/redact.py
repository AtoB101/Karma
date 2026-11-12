"""脱敏工具 —— 凭证永不进日志 / 工具返回。

允许外露：key 指纹、key_id、脱敏钱包地址、状态码、错误分类。
禁止外露：Runtime Key 明文、私钥、助记词、原始签名。
"""

from __future__ import annotations

import hashlib

#: 日志/返回字段白名单。别的地方一律不外露。
SAFE_LOG_FIELDS = (
    "tool",
    "tier",
    "endpoint",
    "http_status",
    "error_class",
    "key_fingerprint",
    "request_id",
)


def fingerprint(secret: str) -> str:
    """不可逆指纹（sha256 前 12 位）。用来「认出是哪把钥匙」而不泄露它。"""
    raw = (secret or "").encode("utf-8")
    if not raw:
        return ""
    return hashlib.sha256(raw).hexdigest()[:12]


def redact_wallet(address: str) -> str:
    """``0x1234...abcd`` —— 保留可辨识的头尾。"""
    addr = (address or "").strip()
    if len(addr) <= 12:
        return "***" if addr else ""
    return addr[:6] + "..." + addr[-4:]
