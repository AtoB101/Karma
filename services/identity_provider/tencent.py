"""
Karma — 腾讯云慧眼（人脸核身）适配器。

接入形态：浏览器直连腾讯云。服务器只用 SecretId/SecretKey 做两件事：
    1. ``DetectAuth`` 开一次核验 → 拿到 BizToken + 浏览器要打开的 Url；
    2. ``GetDetectInfoEnhanced`` 用 BizToken **回查**权威结论。

和阿里云一样：回调只当「去查一下」的信号。判定权在回查那一侧，
伪造一条回调没有任何收益 —— 回查要带服务器密钥。

密钥（服务器 .env）：
    IDENTITY_PROVIDER_TENCENT_SECRET_ID / _SECRET_KEY / _RULE_ID
    IDENTITY_PROVIDER_TENCENT_REGION（默认 ap-guangzhou）

注意：``Text.ErrCode`` 的取值口径要和腾讯云控制台上那个 RuleId 的配置对齐后再上线
（0 = 通过）。密钥一到位，用真实响应核对一次即可，代码结构不用动。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any

from services.identity_provider.base import (
    OUTCOME_PENDING,
    OUTCOME_REJECTED,
    OUTCOME_VERIFIED,
    ProviderDecision,
    ProviderError,
)
from services.identity_provider.http import post_json
from services.identity_provider.signature import sha256_hex

SERVICE = "faceid"
HOST = "faceid.tencentcloudapi.com"
API_VERSION = "2018-03-01"
INIT_ACTION = "DetectAuth"
DESCRIBE_ACTION = "GetDetectInfoEnhanced"
SESSION_TTL_SECONDS = 1800


def _hmac_sha256(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def tc3_authorization(
    *, secret_id: str, secret_key: str, action: str, payload: str, timestamp: int, region: str
) -> str:
    """腾讯云 TC3-HMAC-SHA256 签名（官方签名字典序，逐段可核对）。"""
    date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    canonical_headers = "content-type:application/json; charset=utf-8\nhost:%s\n" % HOST
    signed_headers = "content-type;host"
    hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = "\n".join(
        ["POST", "/", "", canonical_headers, signed_headers, hashed_payload]
    )
    credential_scope = "%s/%s/tc3_request" % (date, SERVICE)
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(timestamp),
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    secret_date = _hmac_sha256(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, SERVICE)
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(
        secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return (
        "TC3-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s"
        % (secret_id, credential_scope, signed_headers, signature)
    )


class TencentIdentityProvider:
    name = "tencent"

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    # ---------------------------------------------------------------- 配置

    def _secret_id(self) -> str:
        return (getattr(self._settings, "identity_provider_tencent_secret_id", "") or "").strip()

    def _secret_key(self) -> str:
        return (getattr(self._settings, "identity_provider_tencent_secret_key", "") or "").strip()

    def _rule_id(self) -> str:
        return (getattr(self._settings, "identity_provider_tencent_rule_id", "") or "").strip()

    def _region(self) -> str:
        return (getattr(self._settings, "identity_provider_tencent_region", "") or "ap-guangzhou").strip()

    def missing_config(self) -> list[str]:
        missing = []
        if not self._secret_id():
            missing.append("IDENTITY_PROVIDER_TENCENT_SECRET_ID")
        if not self._secret_key():
            missing.append("IDENTITY_PROVIDER_TENCENT_SECRET_KEY")
        if not self._rule_id():
            missing.append("IDENTITY_PROVIDER_TENCENT_RULE_ID")
        return missing

    def is_configured(self) -> bool:
        return not self.missing_config()

    def supports_callback(self) -> bool:
        return True

    def supports_pull(self) -> bool:
        return True

    # ---------------------------------------------------------------- RPC

    async def _call(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps({k: v for k, v in params.items() if v is not None}, separators=(",", ":"))
        timestamp = int(time.time())
        headers = {
            "Authorization": tc3_authorization(
                secret_id=self._secret_id(),
                secret_key=self._secret_key(),
                action=action,
                payload=payload,
                timestamp=timestamp,
                region=self._region(),
            ),
            "Content-Type": "application/json; charset=utf-8",
            "Host": HOST,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": API_VERSION,
            "X-TC-Region": self._region(),
        }
        body = await post_json("https://" + HOST, json.loads(payload), headers)
        response = (body or {}).get("Response") or {}
        error = response.get("Error") or {}
        if error:
            # 错误信息里可能带用户标识，只留错误码。
            raise ProviderError(502, "tencent returned %s" % (error.get("Code") or "Error"))
        return response

    # ---------------------------------------------------------------- 会话

    async def create_session(
        self,
        *,
        identity_id: str,
        session_id: str,
        callback_url: str,
        return_url: str | None = None,
    ) -> dict[str, Any]:
        response = await self._call(
            INIT_ACTION,
            {
                "RuleId": self._rule_id(),
                "BizToken": "",
                # 腾讯云把 Extra 原样回传：用它把回调绑回这一次核验。
                "Extra": json.dumps({"identity_id": identity_id}, separators=(",", ":")),
                "RedirectUrl": return_url or callback_url,
            },
        )
        biz_token = str(response.get("BizToken") or "").strip()
        url = str(response.get("Url") or "").strip()
        if not biz_token:
            raise ProviderError(502, "tencent did not return a BizToken")
        return {
            "provider": self.name,
            "session_id": session_id,
            "provider_session_id": biz_token,
            "mode": "both",
            "verify_url": url or None,
            "callback_url": callback_url,
            "return_url": return_url,
            "expires_in_seconds": SESSION_TTL_SECONDS,
        }

    # ---------------------------------------------------------------- 回调

    async def parse_callback(self, *, headers: Any, raw_body: bytes) -> ProviderDecision:
        """回调**不作定论**：只取 BizToken，然后由调用方回查。"""
        try:
            body = json.loads(raw_body or b"{}")
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(400, "callback body is not valid JSON") from exc
        if not isinstance(body, dict):
            raise ProviderError(400, "callback body must be a JSON object")
        biz_token = str(
            body.get("BizToken") or body.get("bizToken") or (body.get("Response") or {}).get("BizToken") or ""
        ).strip()
        if not biz_token:
            raise ProviderError(400, "callback body is missing BizToken")
        return ProviderDecision(
            outcome=OUTCOME_PENDING,
            provider_session_id=biz_token,
            raw_digest=sha256_hex(raw_body),
            source="callback",
            requires_pull=True,
        ).normalized()

    # ---------------------------------------------------------------- 回查

    async def fetch_result(self, *, provider_session_id: str) -> ProviderDecision:
        response = await self._call(
            DESCRIBE_ACTION,
            {
                "BizToken": provider_session_id,
                "RuleId": self._rule_id(),
                "InfoType": {"Text": True},
            },
        )
        text = response.get("Text") or {}
        if "ErrCode" not in text:
            return ProviderDecision(
                outcome=OUTCOME_PENDING,
                provider_session_id=provider_session_id,
                source="poll",
            ).normalized()
        try:
            err_code = int(text.get("ErrCode"))
        except (TypeError, ValueError):
            return ProviderDecision(
                outcome=OUTCOME_PENDING,
                provider_session_id=provider_session_id,
                reason_code=str(text.get("ErrCode"))[:64],
                source="poll",
            ).normalized()
        return ProviderDecision(
            outcome=OUTCOME_VERIFIED if err_code == 0 else OUTCOME_REJECTED,
            provider_session_id=provider_session_id,
            reason_code=str(err_code),
            source="poll",
        ).normalized()
