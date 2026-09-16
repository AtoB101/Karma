"""
Karma — 阿里云实人认证（Cloud Auth）适配器。

接入形态：浏览器直连阿里云。服务器只用 AccessKey 做两件事：
    1. ``InitFaceVerify`` 开一次核验 → 拿到 CertifyId + 浏览器要打开的 CertifyUrl；
    2. ``DescribeFaceVerify`` 用 CertifyId **回查**权威结论。

为什么回调只当「去查一下」的信号：阿里云这条链路的判定权在 DescribeFaceVerify 上。
回调里的 CertifyId 谁都能抄，但回查必须带服务器 AccessKey —— 伪造一条「通过」是没用的。

密钥（服务器 .env）：
    IDENTITY_PROVIDER_ALIYUN_ACCESS_KEY_ID / _SECRET / _SCENE_ID
    IDENTITY_PROVIDER_ALIYUN_ENDPOINT（默认 cloudauth.aliyuncs.com）
    IDENTITY_PROVIDER_ALIYUN_REGION（默认 cn-hangzhou）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from services.identity_provider.base import (
    OUTCOME_PENDING,
    OUTCOME_REJECTED,
    OUTCOME_VERIFIED,
    ProviderDecision,
    ProviderError,
)
from services.identity_provider.http import post_form
from services.identity_provider.signature import sha256_hex

API_VERSION = "2019-03-07"
INIT_ACTION = "InitFaceVerify"
DESCRIBE_ACTION = "DescribeFaceVerify"
SESSION_TTL_SECONDS = 1800


def percent_encode(value: Any) -> str:
    """阿里云 RPC 签名规定的百分号编码（和 urlencode 的默认写法不同，别混用）。"""
    encoded = quote(str(value), safe="")
    return encoded.replace("+", "%20").replace("*", "%2A").replace("%7E", "~")


def rpc_signature(
    params: dict[str, Any], secret: str, *, method: str = "POST", path: str = "/"
) -> str:
    """阿里云 RPC 风格签名：``Base64(HMAC-SHA1(secret + "&", "POST&%2F&" + 规范化查询串))``。"""
    canonical = "&".join(
        "%s=%s" % (percent_encode(key), percent_encode(params[key])) for key in sorted(params)
    )
    string_to_sign = "%s&%s&%s" % (method.upper(), percent_encode(path), percent_encode(canonical))
    digest = hmac.new(
        (secret + "&").encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1
    ).digest()
    return base64.b64encode(digest).decode("ascii")


class AliyunIdentityProvider:
    name = "aliyun"

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    # ---------------------------------------------------------------- 配置

    def _key_id(self) -> str:
        return (getattr(self._settings, "identity_provider_aliyun_access_key_id", "") or "").strip()

    def _key_secret(self) -> str:
        return (
            getattr(self._settings, "identity_provider_aliyun_access_key_secret", "") or ""
        ).strip()

    def _scene_id(self) -> str:
        return (getattr(self._settings, "identity_provider_aliyun_scene_id", "") or "").strip()

    def _endpoint(self) -> str:
        host = (
            getattr(self._settings, "identity_provider_aliyun_endpoint", "")
            or "cloudauth.aliyuncs.com"
        ).strip()
        return host if host.startswith("http") else "https://" + host

    def _region(self) -> str:
        return (getattr(self._settings, "identity_provider_aliyun_region", "") or "cn-hangzhou").strip()

    def missing_config(self) -> list[str]:
        missing = []
        if not self._key_id():
            missing.append("IDENTITY_PROVIDER_ALIYUN_ACCESS_KEY_ID")
        if not self._key_secret():
            missing.append("IDENTITY_PROVIDER_ALIYUN_ACCESS_KEY_SECRET")
        if not self._scene_id():
            missing.append("IDENTITY_PROVIDER_ALIYUN_SCENE_ID")
        return missing

    def is_configured(self) -> bool:
        return not self.missing_config()

    def supports_callback(self) -> bool:
        return True

    def supports_pull(self) -> bool:
        return True

    # ---------------------------------------------------------------- RPC

    def _signed_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {
            "Action": action,
            "Version": API_VERSION,
            "Format": "JSON",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureVersion": "1.0",
            "SignatureNonce": uuid.uuid4().hex,
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "RegionId": self._region(),
            "AccessKeyId": self._key_id(),
        }
        merged.update({k: v for k, v in params.items() if v not in (None, "")})
        merged["Signature"] = rpc_signature(merged, self._key_secret())
        return merged

    async def _call(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        body = await post_form(self._endpoint() + "/", self._signed_params(action, params))
        if not isinstance(body, dict):
            raise ProviderError(502, "aliyun returned a non-object response")
        if str(body.get("Code") or "Success") != "Success":
            # Message 里可能带用户信息，只留 Code，不留 Message。
            raise ProviderError(502, f"aliyun returned Code={body.get('Code')}")
        return body

    # ---------------------------------------------------------------- 会话

    async def create_session(
        self,
        *,
        identity_id: str,
        session_id: str,
        callback_url: str,
        return_url: str | None = None,
    ) -> dict[str, Any]:
        meta = {
            "certifyId": "",
            "outerOrderNo": session_id,
            "bizCode": "1000000",
            "userId": identity_id,
        }
        # 场景参数（要采几个角度、是否要活体）在阿里云控制台的 SceneId 上配置，
        # 这里只传场景号，避免在代码里复制一份会和控制台漂移的副本。
        body = await self._call(
            INIT_ACTION,
            {
                "SceneId": self._scene_id(),
                "OuterOrderNo": session_id,
                "UserId": identity_id,
                "MetaInfo": json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
            },
        )
        result = body.get("ResultObject") or {}
        certify_id = str(result.get("CertifyId") or "").strip()
        certify_url = str(result.get("CertifyUrl") or "").strip()
        if not certify_id:
            raise ProviderError(502, "aliyun did not return a CertifyId")
        return {
            "provider": self.name,
            "session_id": session_id,
            "provider_session_id": certify_id,
            "mode": "both",
            "verify_url": certify_url or None,
            "callback_url": callback_url,
            "return_url": return_url,
            "expires_in_seconds": SESSION_TTL_SECONDS,
        }

    # ---------------------------------------------------------------- 回调

    async def parse_callback(self, *, headers: Any, raw_body: bytes) -> ProviderDecision:
        """回调**不作定论**：只从里面取 CertifyId，然后由调用方去回查。"""
        try:
            body = json.loads(raw_body or b"{}")
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(400, "callback body is not valid JSON") from exc
        if not isinstance(body, dict):
            raise ProviderError(400, "callback body must be a JSON object")
        certify_id = str(body.get("CertifyId") or body.get("certifyId") or "").strip()
        if not certify_id:
            raise ProviderError(400, "callback body is missing CertifyId")
        return ProviderDecision(
            outcome=OUTCOME_PENDING,
            session_id=str(body.get("OuterOrderNo") or "").strip() or None,
            provider_session_id=certify_id,
            raw_digest=sha256_hex(raw_body),
            source="callback",
            requires_pull=True,
        ).normalized()

    # ---------------------------------------------------------------- 回查

    async def fetch_result(self, *, provider_session_id: str) -> ProviderDecision:
        body = await self._call(
            DESCRIBE_ACTION,
            {"SceneId": self._scene_id(), "CertifyId": provider_session_id},
        )
        result = body.get("ResultObject") or {}
        passed = str(result.get("Passed") or "").strip().upper()
        sub_code = str(result.get("SubCode") or "").strip() or None
        if passed == "T":
            outcome = OUTCOME_VERIFIED
        elif passed == "F":
            outcome = OUTCOME_REJECTED
        else:
            outcome = OUTCOME_PENDING
        return ProviderDecision(
            outcome=outcome,
            provider_session_id=provider_session_id,
            reason_code=sub_code or (passed or "UNKNOWN"),
            source="poll",
        ).normalized()
