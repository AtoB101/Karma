"""
Karma — Persona 适配器（海外：Persona / 同类 hosted flow）。

接入形态：**浏览器直连 Persona**。我们只做两件事：
    1. 用服务器密钥开一次 inquiry，把 hosted 链接交给浏览器；
    2. 收 Persona 的 webhook（``Persona-Signature`` 做 HMAC-SHA256 验签），把结论归一化。
证件影像与人脸影像从头到尾直接落在 Persona，Karma 不经手、不接收。

密钥（服务器 .env，非机密项写在 .env.example 里）：
    IDENTITY_PROVIDER_PERSONA_API_KEY
    IDENTITY_PROVIDER_PERSONA_TEMPLATE_ID
    IDENTITY_PROVIDER_PERSONA_WEBHOOK_SECRET
"""
from __future__ import annotations

import json
from typing import Any

from services.identity_provider.base import (
    OUTCOME_PENDING,
    OUTCOME_REJECTED,
    OUTCOME_VERIFIED,
    ProviderDecision,
    ProviderError,
)
from services.identity_provider.http import get_json, post_json
from services.identity_provider.signature import (
    header_value,
    sha256_hex,
    verify_timestamped_hmac,
)

API_BASE = "https://withpersona.com/api/v1"
SIGNATURE_HEADER = "persona-signature"
#: Persona 的判定枚举 → Karma 的三态。未知状态一律按 pending 处理（宁可等，不许误判通过）。
STATUS_MAP = {
    "completed": OUTCOME_VERIFIED,
    "declined": OUTCOME_REJECTED,
    "failed": OUTCOME_REJECTED,
    "expired": OUTCOME_REJECTED,
    "created": OUTCOME_PENDING,
    "pending": OUTCOME_PENDING,
    "needs_review": OUTCOME_PENDING,
}
SESSION_TTL_SECONDS = 1800


class PersonaIdentityProvider:
    name = "persona"

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    # ---------------------------------------------------------------- 配置

    def _api_key(self) -> str:
        return (getattr(self._settings, "identity_provider_persona_api_key", "") or "").strip()

    def _template_id(self) -> str:
        return (
            getattr(self._settings, "identity_provider_persona_template_id", "") or ""
        ).strip()

    def _webhook_secret(self) -> str:
        return (
            getattr(self._settings, "identity_provider_persona_webhook_secret", "") or ""
        ).strip()

    def missing_config(self) -> list[str]:
        missing = []
        if not self._api_key():
            missing.append("IDENTITY_PROVIDER_PERSONA_API_KEY")
        if not self._template_id():
            missing.append("IDENTITY_PROVIDER_PERSONA_TEMPLATE_ID")
        if not self._webhook_secret():
            missing.append("IDENTITY_PROVIDER_PERSONA_WEBHOOK_SECRET")
        return missing

    def is_configured(self) -> bool:
        return not self.missing_config()

    def supports_callback(self) -> bool:
        return True

    def supports_pull(self) -> bool:
        return True

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self._api_key(),
            "Persona-Version": "2023-01-05",
            "Content-Type": "application/json",
        }

    # ---------------------------------------------------------------- 会话

    async def create_session(
        self,
        *,
        identity_id: str,
        session_id: str,
        callback_url: str,
        return_url: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "data": {
                "attributes": {
                    "inquiry-template-id": self._template_id(),
                    # reference-id 会被原样回传：用它把 webhook 绑回这一次核验
                    "reference-id": session_id,
                }
            }
        }
        body = await post_json(API_BASE + "/inquiries", payload, self._headers())
        inquiry_id = str(((body or {}).get("data") or {}).get("id") or "").strip()
        if not inquiry_id:
            raise ProviderError(502, "persona did not return an inquiry id")
        return {
            "provider": self.name,
            "session_id": session_id,
            "provider_session_id": inquiry_id,
            "mode": "both",
            "verify_url": "https://withpersona.com/verify?inquiry-id=" + inquiry_id,
            "callback_url": callback_url,
            "return_url": return_url,
            "expires_in_seconds": SESSION_TTL_SECONDS,
        }

    # ---------------------------------------------------------------- 回调

    def _decision_from_inquiry(self, inquiry: dict[str, Any], *, source: str, raw: bytes | None) -> ProviderDecision:
        attributes = (inquiry or {}).get("attributes") or {}
        status = str(attributes.get("status") or "").strip().lower()
        outcome = STATUS_MAP.get(status)
        if outcome is None:
            raise ProviderError(502, f"persona returned an unknown inquiry status: {status!r}")
        return ProviderDecision(
            outcome=outcome,
            session_id=attributes.get("reference-id"),
            provider_session_id=str((inquiry or {}).get("id") or "").strip() or None,
            reason_code=status,
            occurred_at=attributes.get("completed-at") or attributes.get("updated-at"),
            raw_digest=sha256_hex(raw) if raw is not None else None,
            source=source,
        ).normalized()

    async def parse_callback(self, *, headers: Any, raw_body: bytes) -> ProviderDecision:
        verify_timestamped_hmac(
            secret=self._webhook_secret(),
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

        data = body.get("data") or {}
        if not isinstance(data, dict):
            raise ProviderError(400, "callback body is missing data")
        attributes = data.get("attributes") or {}

        # 事件形态：payload 里才是 inquiry 本身。
        payload = attributes.get("payload") if isinstance(attributes, dict) else None
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return self._decision_from_inquiry(payload["data"], source="callback", raw=raw_body)
        # inquiry 形态：data 本身就是 inquiry。
        if str(data.get("type") or "").strip().lower() == "inquiry":
            return self._decision_from_inquiry(data, source="callback", raw=raw_body)
        raise ProviderError(400, "callback body does not carry an inquiry result")

    # ---------------------------------------------------------------- 回查

    async def fetch_result(self, *, provider_session_id: str) -> ProviderDecision:
        body = await get_json(API_BASE + "/inquiries/" + provider_session_id, self._headers())
        inquiry = (body or {}).get("data") or {}
        if not isinstance(inquiry, dict) or not inquiry:
            raise ProviderError(502, "persona did not return the inquiry")
        return self._decision_from_inquiry(inquiry, source="poll", raw=None)
