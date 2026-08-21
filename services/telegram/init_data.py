"""Telegram WebApp initData server-side verification.

Never trust frontend-provided telegram user id without verifying initData.
Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramUser:
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    is_premium: bool = False


@dataclass(frozen=True)
class VerifiedInitData:
    user: TelegramUser
    auth_date: int
    query_id: str | None = None
    chat_instance: str | None = None
    chat_type: str | None = None
    raw: dict[str, str] | None = None


def _bot_token() -> str:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        # Dev-only fallback — production MUST set TELEGRAM_BOT_TOKEN
        if (os.getenv("KARMA_ENV") or os.getenv("ENV") or "dev").lower() in {"dev", "test", "local"}:
            return os.getenv("TELEGRAM_BOT_TOKEN_DEV", "dev-bot-token-not-for-prod")
        raise InitDataError("TELEGRAM_BOT_TOKEN not configured")
    return token


def validate_init_data(
    init_data: str,
    *,
    bot_token: str | None = None,
    max_age_seconds: int = 86400,
    now: int | None = None,
) -> VerifiedInitData:
    """Validate Telegram WebApp initData. Raises InitDataError on failure."""
    if not init_data or not isinstance(init_data, str):
        raise InitDataError("init_data required")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    recv_hash = pairs.pop("hash", None)
    if not recv_hash:
        raise InitDataError("missing hash")

    # Optional: Telegram added signature field for third-party; ignore for classic WebApp hash
    pairs.pop("signature", None)

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    token = bot_token or _bot_token()
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    calc = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, recv_hash):
        raise InitDataError("invalid initData hash")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("invalid auth_date") from exc
    ts = int(now if now is not None else time.time())
    if auth_date <= 0 or (ts - auth_date) > max_age_seconds:
        raise InitDataError("initData expired")

    user_raw = pairs.get("user")
    if not user_raw:
        raise InitDataError("missing user")
    try:
        user_obj = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise InitDataError("invalid user json") from exc
    if not isinstance(user_obj, dict) or "id" not in user_obj:
        raise InitDataError("user.id required")

    user = TelegramUser(
        id=int(user_obj["id"]),
        username=user_obj.get("username"),
        first_name=user_obj.get("first_name"),
        last_name=user_obj.get("last_name"),
        language_code=user_obj.get("language_code"),
        is_premium=bool(user_obj.get("is_premium", False)),
    )
    return VerifiedInitData(
        user=user,
        auth_date=auth_date,
        query_id=pairs.get("query_id"),
        chat_instance=pairs.get("chat_instance"),
        chat_type=pairs.get("chat_type"),
        raw=pairs,
    )


def build_dev_init_data(
    *,
    user_id: int = 10001,
    username: str = "karma_dev",
    first_name: str = "Karma",
    bot_token: str | None = None,
    auth_date: int | None = None,
) -> str:
    """Build a valid initData string for local/dev tests."""
    token = bot_token or _bot_token()
    ad = int(auth_date if auth_date is not None else time.time())
    user = json.dumps(
        {"id": user_id, "username": username, "first_name": first_name},
        separators=(",", ":"),
    )
    pairs = {"auth_date": str(ad), "user": user}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    digest = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    from urllib.parse import urlencode

    return urlencode({**pairs, "hash": digest})
