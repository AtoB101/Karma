"""
Karma — 实名 / 活体服务适配层的契约。

适配器只做三件事，别的一律不做：
    create_session()  给浏览器一个「去哪儿做核验」的入口（会话号 + 链接 / 参数）
    parse_callback()  校验服务商回调的**签名**，把结论归一化
    fetch_result()    拿服务商那边的权威结论（pull 型服务商：回调只当作「去查一下」的信号）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# 归一化结论：业务层只认这三个，服务商的原始枚举不许透出去。
OUTCOME_VERIFIED = "verified"
OUTCOME_REJECTED = "rejected"
OUTCOME_PENDING = "pending"
OUTCOMES = (OUTCOME_VERIFIED, OUTCOME_REJECTED, OUTCOME_PENDING)

# 「为什么被拒」的短原因码：只留服务商自己的码，不留自然语言（里面常带姓名）。
REASON_MAX_CHARS = 64
PROVIDER_SESSION_ID_MAX_CHARS = 128


class ProviderError(Exception):
    """适配层错误，带 HTTP 状态，路由层直接翻译成响应。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ProviderNotConfigured(ProviderError):
    """没接服务商 / 密钥没配齐。**绝不允许静默降级成「已核验」。**"""


class ProviderSignatureError(ProviderError):
    """回调签名或时间戳不对：401，而且一条记录都不写。"""


@dataclass(frozen=True)
class ProviderDecision:
    """归一化之后的一次判定。"""

    outcome: str
    #: 服务商回传的「业务用户号」= 我们的 identity_id（发起时由我们塞进去）
    identity_id: str | None = None
    #: 我们签发的会话号（服务商原样带回来，用来绑定到具体这一次核验）
    session_id: str | None = None
    #: 服务商自己那边的会话号（CertifyId / BizToken / inquiry id）
    provider_session_id: str | None = None
    #: 服务商的原因码，短字符串
    reason_code: str | None = None
    risk_level: str | None = None
    occurred_at: str | None = None
    #: 原始报文的 SHA-256：只留指纹，报文本身不留存
    raw_digest: str | None = None
    #: callback = 服务商推过来的；poll = 我们主动查回来的
    source: str = "callback"
    #: True 表示「这条回调本身不足以定论，必须再去查一次」
    requires_pull: bool = False
    #: 只允许放脱敏后的白名单字段
    extra: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ProviderDecision":
        """把服务商可能带进来的超长字段截断，并挡住非法 outcome。"""
        if self.outcome not in OUTCOMES:
            raise ProviderError(502, f"identity provider returned an unknown outcome: {self.outcome!r}")
        return ProviderDecision(
            outcome=self.outcome,
            identity_id=(self.identity_id or "").strip() or None,
            session_id=(self.session_id or "").strip()[:PROVIDER_SESSION_ID_MAX_CHARS] or None,
            provider_session_id=(self.provider_session_id or "").strip()[
                :PROVIDER_SESSION_ID_MAX_CHARS
            ] or None,
            reason_code=(self.reason_code or "").strip()[:REASON_MAX_CHARS] or None,
            risk_level=(self.risk_level or "").strip()[:REASON_MAX_CHARS] or None,
            occurred_at=(self.occurred_at or "").strip()[:64] or None,
            raw_digest=self.raw_digest,
            source=self.source,
            requires_pull=self.requires_pull,
            extra=dict(self.extra or {}),
        )


@runtime_checkable
class IdentityProvider(Protocol):
    """一个实名 / 活体服务商。"""

    #: 配置里的名字：mock / aliyun / tencent / persona
    name: str

    def is_configured(self) -> bool:
        """密钥是否配齐。没配齐必须报缺哪几项，不能装作能用。"""

    def missing_config(self) -> list[str]:
        """还缺哪些配置项（写给运维看，不含密钥值）。"""

    def supports_callback(self) -> bool:
        """服务商会不会主动推回调。"""

    def supports_pull(self) -> bool:
        """能不能由我们主动去查结论。"""

    async def create_session(
        self, *, identity_id: str, session_id: str, callback_url: str, return_url: str | None = None
    ) -> dict[str, Any]:
        """开一次核验，返回给**浏览器**的东西（会话号、跳转链接、参数）。"""

    async def parse_callback(self, *, headers: Any, raw_body: bytes) -> ProviderDecision:
        """校验回调签名并归一化结论。签名不对一律 ProviderSignatureError。"""

    async def fetch_result(self, *, provider_session_id: str) -> ProviderDecision:
        """去服务商那边查这件事的权威结论。"""
