"""WhatsApp Cloud API 客户端 + webhook 验签。

与 Telegram 的两处关键差异，都在这个文件里收口：

1. **入站验签**：WhatsApp 用 ``X-Hub-Signature-256``（对**原始报文**做
   HMAC-SHA256），不是 Telegram 的静态 secret header。所以路由层必须拿
   ``await request.body()`` 的原样字节来验，不能先 json 解析再重序列化。
2. **握手**：订阅时 Meta 会 ``GET`` 过来带 ``hub.mode`` / ``hub.verify_token`` /
   ``hub.challenge``，token 对上了才回 challenge。

fail-closed：``WHATSAPP_APP_SECRET`` 没配 → ``verify_signature`` 一律 ``False``
（路由据此回 503），绝不接受未验签的报文。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://graph.facebook.com/v21.0"
_SIGNATURE_PREFIX = "sha256="


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def api_base() -> str:
    return (_env("WHATSAPP_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def access_token() -> str:
    return _env("WHATSAPP_ACCESS_TOKEN")


def phone_number_id() -> str:
    return _env("WHATSAPP_PHONE_NUMBER_ID")


def app_secret() -> str:
    """用来验 ``X-Hub-Signature-256`` 的 App Secret。"""
    return _env("WHATSAPP_APP_SECRET")


def verify_token() -> str:
    """``hub.verify_token`` 期望值。"""
    return _env("WHATSAPP_VERIFY_TOKEN")


def webhook_configured() -> bool:
    """验签凭据齐了没有。没齐 → 路由回 503，而不是「先放过来」。"""
    return bool(app_secret())


def send_configured() -> bool:
    return bool(access_token() and phone_number_id())


def _dev_env() -> bool:
    env = (_env("KARMA_ENV") or _env("ENV") or "dev").lower()
    return env in {"dev", "test", "local"}


def send_enabled() -> bool:
    """dev/test/local 默认**不发**真实消息；要发得显式打开。"""
    if _env("WHATSAPP_SEND_DISABLED").lower() in {"1", "true", "yes"}:
        return False
    if _dev_env():
        return _env("WHATSAPP_SEND_IN_DEV").lower() in {"1", "true", "yes"}
    return True


def verify_signature(raw_body: bytes, header: str | None) -> bool:
    """常数时间比对 ``sha256=`` HMAC；没配 App Secret 一律 False。"""
    secret = app_secret()
    if not secret:
        return False
    if not header or not isinstance(header, str):
        return False
    candidate = header.strip()
    if not candidate.startswith(_SIGNATURE_PREFIX):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body or b"", hashlib.sha256).hexdigest()
    return hmac.compare_digest(candidate[len(_SIGNATURE_PREFIX):].lower(), expected)


def check_hub_challenge(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    """订阅握手：token 对上且 mode == subscribe 才回 challenge，否则 ``None``。"""
    expected = verify_token()
    if not expected:
        return None
    if (mode or "").strip().lower() != "subscribe":
        return None
    if not token or not hmac.compare_digest(str(token), expected):
        return None
    return str(challenge or "")


def send_message(to: str, text: str, *, buttons: tuple[tuple[str, str], ...] = ()) -> dict[str, Any]:
    """发一条 WhatsApp 消息。最多 3 个按钮（Cloud API 硬限制），标题 ≤ 20 字。"""
    if not send_configured():
        raise RuntimeError("whatsapp send is not configured")
    url = f"{api_base()}/{phone_number_id()}/messages"
    if buttons:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": payload_id, "title": label[:20]}}
                        for label, payload_id in buttons[:3]
                    ]
                },
            },
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {access_token()}"},
        )
        resp.raise_for_status()
        return resp.json()