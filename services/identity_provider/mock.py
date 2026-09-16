"""
Karma — 本地模拟服务商（测试 / 本地开发用）。

它存在的意义：把「发起核验 → 服务商判定 → 回调 → 自动置位」整条链路**离线**跑通，
包括签名校验这一段（本地模拟也用真签名，不是开口子跳过校验）。

安全边界：
* 它只在 ``IDENTITY_PROVIDER=mock`` 时才会被选中；
* 生产环境（APP_ENV=production）禁止选它，settings 启动时就会拒绝。
"""
from __future__ import annotations

import json
from typing import Any

from services.identity_provider.base import (
    OUTCOMES,
    ProviderDecision,
    ProviderError,
    ProviderNotConfigured,
)
from services.identity_provider.signature import (
    header_value,
    sha256_hex,
    verify_timestamped_hmac,
)

SIGNATURE_HEADER = "x-karma-provider-signature"
SESSION_TTL_SECONDS = 1800


class MockIdentityProvider:
    """把服务商换成「本机模拟」：结论由调用方通过签名回调直接给出。"""

    name = "mock"

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    # ---------------------------------------------------------------- 配置

    def _secret(self) -> str:
        return (getattr(self._settings, "identity_provider_callback_secret", "") or "").strip()

    def missing_config(self) -> list[str]:
        return [] if self._secret() else ["IDENTITY_PROVIDER_CALLBACK_SECRET"]

    def is_configured(self) -> bool:
        return not self.missing_config()

    def supports_callback(self) -> bool:
        return True

    def supports_pull(self) -> bool:
        return False

    # ---------------------------------------------------------------- 会话

    async def create_session(
        self,
        *,
        identity_id: str,
        session_id: str,
        callback_url: str,
        return_url: str | None = None,
    ) -> dict[str, Any]:
        if not self.is_configured():
            raise ProviderNotConfigured(
                503,
                "mock identity provider needs IDENTITY_PROVIDER_CALLBACK_SECRET "
                "to sign its callbacks",
            )
        return {
            "provider": self.name,
            "session_id": session_id,
            "provider_session_id": "mock-" + session_id,
            "mode": "callback",
            "verify_url": None,
            "callback_url": callback_url,
            "return_url": return_url,
            "expires_in_seconds": SESSION_TTL_SECONDS,
            "note": "本地模拟：结论由 POST 到 callback_url 的签名报文给出（见 tests）。",
        }

    # ---------------------------------------------------------------- 回调

    async def parse_callback(self, *, headers: Any, raw_body: bytes) -> ProviderDecision:
        verify_timestamped_hmac(
            secret=self._secret(),
            raw_body=raw_body,
            header=header_value(headers, SIGNATURE_HEADER),
            tolerance_seconds=int(
                getattr(self._settings, "identity_provider_callback_tolerance_seconds", 300) or 300
            ),
        )
        try:
            body = json.loads(raw_body or b"{}")
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(400, "callback body is not valid JSON") from exc
        if not isinstance(body, dict):
            raise ProviderError(400, "callback body must be a JSON object")

        outcome = str(body.get("outcome") or "").strip().lower()
        if outcome not in OUTCOMES:
            raise ProviderError(400, "callback body must carry outcome=verified|rejected|pending")

        def pick(*names: str) -> str | None:
            for key in names:
                value = body.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return None

        return ProviderDecision(
            outcome=outcome,
            identity_id=pick("identity_id", "biz_user_id"),
            session_id=pick("session_id", "reference"),
            provider_session_id=pick("provider_session_id"),
            reason_code=pick("reason_code"),
            risk_level=pick("risk_level"),
            occurred_at=pick("occurred_at"),
            raw_digest=sha256_hex(raw_body),
            source="callback",
        ).normalized()

    async def fetch_result(self, *, provider_session_id: str) -> ProviderDecision:
        raise ProviderError(501, "mock identity provider has no result API")
