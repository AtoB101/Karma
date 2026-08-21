"""Telegram Bot webhook + deep-link binding helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from typing import Any
from urllib.parse import urlencode


def bot_token() -> str:
    return (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN_DEV") or "dev-bot-token-not-for-prod").strip()


def miniapp_url() -> str:
    return (os.getenv("TELEGRAM_MINIAPP_URL") or "https://t.me/KarmaBot/app").rstrip("/")


def deep_link_start(*, identity_id: str | None = None, action: str = "bind") -> str:
    """t.me deep link into bot with start payload."""
    bot = (os.getenv("TELEGRAM_BOT_USERNAME") or "KarmaBot").lstrip("@")
    payload = action
    if identity_id:
        payload = f"{action}_{identity_id}"
    # Telegram start param max 64 chars
    payload = payload[:64]
    return f"https://t.me/{bot}?start={payload}"


def miniapp_deeplink(*, startapp: str | None = None) -> str:
    q = urlencode({"startapp": startapp}) if startapp else ""
    base = miniapp_url()
    return f"{base}?{q}" if q else base


def verify_webhook_secret(header_token: str | None) -> bool:
    expected = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if not expected:
        # allow in dev/test
        env = (os.getenv("KARMA_ENV") or os.getenv("ENV") or "dev").lower()
        return env in {"dev", "test", "local"}
    return bool(header_token) and hmac.compare_digest(header_token, expected)


def handle_update(update: dict[str, Any]) -> dict[str, Any]:
    """Process a Telegram Update. Returns response hints for Bot API sendMessage."""
    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    text = (message.get("text") or "").strip()
    chat_id = chat.get("id")
    from_user = message.get("from") or {}

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        payload = parts[1] if len(parts) > 1 else ""
        identity_id = None
        action = "open"
        if payload.startswith("bind_"):
            action = "bind"
            identity_id = payload[len("bind_") :]
        app_url = miniapp_deeplink(startapp=payload or None)
        reply = (
            "Welcome to Karma.\n"
            "Open the Mini App to continue Chat / Identity / Settlement.\n"
            f"{app_url}"
        )
        return {
            "ok": True,
            "action": action,
            "identity_id": identity_id,
            "chat_id": chat_id,
            "telegram_user_id": from_user.get("id"),
            "reply_text": reply,
            "miniapp_url": app_url,
        }

    if text in {"/app", "/miniapp"}:
        return {
            "ok": True,
            "action": "open",
            "chat_id": chat_id,
            "reply_text": f"Open Karma Mini App:\n{miniapp_url()}",
            "miniapp_url": miniapp_url(),
        }

    return {
        "ok": True,
        "action": "noop",
        "chat_id": chat_id,
        "reply_text": "Send /app to open Karma Mini App, or /start to begin.",
    }
