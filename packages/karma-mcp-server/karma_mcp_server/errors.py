"""MCP 层的错误分类。

铁律：**失败永不转成成功**。这里只做归类，不做吞掉 —— 客户端据此决定
「重试 / 向用户解释 / 放弃」。

分类与 ``docs/mcp/karma-mcp-architecture.md`` §8 一一对应。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ErrorClass(str, Enum):
    TRANSPORT = "transport"  # 连不上 / 超时
    UNAUTHORIZED = "unauthorized"  # 无 key / key 无效 / 验签失败
    NOT_ACTIVATED = "not_activated"  # key 已铸但未被主人激活
    FORBIDDEN = "forbidden"  # 有权限但边界不允许
    CONFLICT = "conflict"  # 同 nonce/键换了内容；重复交易
    RATE_LIMITED = "rate_limited"  # 按 key 的写限速
    INVALID = "invalid"  # 参数校验失败
    BACKEND = "backend"  # 后端 5xx


#: 允许重试的分类。写操作重试**必须**复用同一幂等键（client_nonce / Idempotency-Key）。
RETRYABLE = frozenset({ErrorClass.TRANSPORT, ErrorClass.RATE_LIMITED, ErrorClass.BACKEND})

#: 「未激活」的特征串 —— 后端用 403 + 这段文字表示「主人还没在操作台输配对码」。
_ACTIVATION_MARKERS = ("activat", "matching code", "agent_pending", "bind")


def classify_http_status(status: int, detail: str = "") -> ErrorClass:
    """HTTP 状态 + 后端 detail → 错误分类。"""
    text = (detail or "").lower()
    if status == 401:
        return ErrorClass.UNAUTHORIZED
    if status == 403:
        if any(marker in text for marker in _ACTIVATION_MARKERS):
            return ErrorClass.NOT_ACTIVATED
        return ErrorClass.FORBIDDEN
    if status == 409:
        return ErrorClass.CONFLICT
    if status == 429:
        return ErrorClass.RATE_LIMITED
    if 400 <= status < 500:
        return ErrorClass.INVALID
    return ErrorClass.BACKEND


def is_retryable(error_class: ErrorClass) -> bool:
    return error_class in RETRYABLE


@dataclass(frozen=True)
class ErrorInfo:
    error_class: ErrorClass
    message: str
    http_status: int | None = None
    retryable: bool = False
    next_step: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "class": self.error_class.value,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.http_status is not None:
            out["http_status"] = self.http_status
        if self.next_step:
            out["next_step"] = self.next_step
        return out


_NEXT_STEP = {
    ErrorClass.UNAUTHORIZED: "重新执行 karma_connect 完成配对",
    ErrorClass.NOT_ACTIVATED: "请主人在 Karma 操作台输入配对码激活这把钥匙",
    ErrorClass.FORBIDDEN: "该操作超出已授权边界；如确需，请主人调整授权",
    ErrorClass.CONFLICT: "请使用新的 client_nonce 重新发起，不要重复提交同一请求",
    ErrorClass.RATE_LIMITED: "稍后重试（退避）",
    ErrorClass.INVALID: "修正参数后重试",
}


class KarmaToolError(Exception):
    """工具层的结构化异常。``as_dict`` 是唯一对外形态。"""

    def __init__(
        self,
        error_class: ErrorClass,
        message: str,
        *,
        http_status: int | None = None,
        retryable: bool | None = None,
        next_step: str | None = None,
    ) -> None:
        super().__init__(message)
        self.info = ErrorInfo(
            error_class=error_class,
            message=message,
            http_status=http_status,
            retryable=is_retryable(error_class) if retryable is None else retryable,
            next_step=next_step if next_step is not None else _NEXT_STEP.get(error_class),
        )

    @property
    def error_class(self) -> ErrorClass:
        return self.info.error_class

    def as_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": self.info.as_dict()}


def ok(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """成功返回。**不得**用它包装失败。"""
    out: dict[str, Any] = {"ok": True}
    if payload:
        out.update(payload)
    return out
