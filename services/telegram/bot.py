"""Telegram Bot webhook + deep-link binding helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


def bot_token() -> str:
    return (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN_DEV") or "dev-bot-token-not-for-prod").strip()


def telegram_api_base() -> str:
    return (os.getenv("TELEGRAM_API_BASE") or "https://api.telegram.org").rstrip("/")


def _send_enabled() -> bool:
    """Outbound sendMessage is only attempted in non-dev envs (or when explicitly enabled)."""
    if os.getenv("TELEGRAM_BOT_DISABLE_SEND", "").strip().lower() in {"1", "true", "yes"}:
        return False
    env = (os.getenv("KARMA_ENV") or os.getenv("ENV") or "dev").lower()
    if env in {"dev", "test", "local"}:
        return os.getenv("TELEGRAM_BOT_SEND_IN_DEV", "").strip().lower() in {"1", "true", "yes"}
    return True


def send_message(chat_id: int | str, text: str, *, reply_markup: dict | None = None) -> dict:
    """Call Telegram Bot API sendMessage and return the parsed API response."""
    url = f"{telegram_api_base()}/bot{bot_token()}/sendMessage"
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


def _deliver_reply(result: dict[str, Any]) -> dict[str, Any]:
    """Actually send ``reply_text`` to ``chat_id`` via the Bot API; record delivery status."""
    if not _send_enabled():
        result["sent"] = False
        result["send_skipped"] = "outbound send disabled for this environment"
        return result
    chat_id = result.get("chat_id")
    reply_text = result.get("reply_text")
    if not chat_id or not reply_text:
        result["sent"] = False
        return result
    try:
        api_result = send_message(chat_id, reply_text, reply_markup=result.get("reply_markup"))
        result["sent"] = bool(api_result.get("ok"))
        result["send_result"] = api_result
    except Exception as exc:  # noqa: BLE001
        # Never fail the webhook on delivery errors — Telegram retries otherwise.
        logger.warning("telegram_send_message_failed: %s", exc)
        result["sent"] = False
        result["send_error"] = str(exc)
    return result


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


def setup_bot_commands() -> dict:
    """注册 Bot 命令菜单（用户在 TG 里看到的功能入口）。"""
    commands = [
        {"command": "start", "description": "打开主菜单 / 通过邀请链接进入"},
        {"command": "sync", "description": "① 同步官网认证账户"},
        {"command": "receipts", "description": "② 收款明细"},
        {"command": "payments", "description": "③ 付款订单"},
        {"command": "orders", "description": "④ 正在进行的订单"},
        {"command": "disputes", "description": "⑤ 仲裁争议订单"},
        {"command": "points", "description": "⑥ 我的积分"},
        {"command": "invite", "description": "⑦ 邀请码 & 下级"},
    ]
    url = f"{telegram_api_base()}/bot{bot_token()}/setMyCommands"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json={"commands": commands})
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("setup_bot_commands_failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def handle_update(update: dict[str, Any]) -> dict[str, Any]:
    """Process a Telegram Update, deliver the reply via Bot API sendMessage, and return status."""
    # inline 按钮回调（菜单 + 商家推荐选择等）
    callback = update.get("callback_query")
    if callback:
        from services.telegram import concierge  # 延迟导入避免环

        return _deliver_reply(concierge.handle_callback(callback))

    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    text = (message.get("text") or "").strip()
    chat_id = chat.get("id")
    from_user = message.get("from") or {}
    tg_user_id = int(from_user.get("id") or 0)

    from services.telegram import concierge  # 延迟导入避免环

    # /start [payload] —— 主入口（支持 ref_<invite_code> 邀请链接）
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        payload = parts[1] if len(parts) > 1 else ""

        # 邀请码 deep link：/start ref_<CODE>
        if payload.startswith("ref_"):
            invite_code = payload[len("ref_"):]
            from services.identity_gateway import store as identity_store
            referrer = identity_store.get_by_invite_code(invite_code)
            if referrer and tg_user_id:
                # 记录 referred_by（用户后续认证时带上）
                from services.identity_gateway import store as identity_store
                # 如果用户已有身份，直接关联
                existing = identity_store.get_by_telegram(tg_user_id)
                if existing and not existing.referred_by:
                    existing.referred_by = invite_code
                    identity_store._persist()
        elif payload.startswith("bind_"):
            # 绑定 deep link：引导到操作台
            identity_id = payload[len("bind_"):]
            app_url = miniapp_deeplink(startapp=payload)
            return _deliver_reply({
                "ok": True,
                "action": "bind",
                "identity_id": identity_id,
                "chat_id": chat_id,
                "telegram_user_id": from_user.get("id"),
                "reply_text": (
                    "🔗 绑定 Karma 身份\n\n"
                    "请到操作台完成绑定（聊天里不输入密码）：\n"
                    f"{app_url}"
                ),
                "miniapp_url": app_url,
            })

        # /start 无 payload 或已处理 ref → 出主菜单
        result = concierge.menu_main(tg_user_id)
        result.setdefault("chat_id", chat_id)
        result.setdefault("telegram_user_id", from_user.get("id"))
        return _deliver_reply(result)

    # 命令菜单
    _CMD_MAP = {
        "/menu": concierge.menu_main,
        "/sync": concierge.menu_sync,
        "/receipts": concierge.menu_receipts,
        "/payments": concierge.menu_payments,
        "/orders": concierge.menu_ongoing,
        "/disputes": concierge.menu_disputes,
        "/points": concierge.menu_points,
        "/invite": concierge.menu_invite,
    }
    cmd = text.split()[0].lower() if text else ""
    if cmd in _CMD_MAP:
        result = _CMD_MAP[cmd](tg_user_id)
        result.setdefault("chat_id", chat_id)
        result.setdefault("telegram_user_id", from_user.get("id"))
        return _deliver_reply(result)

    if text in {"/app", "/miniapp"}:
        return _deliver_reply({
            "ok": True,
            "action": "open",
            "chat_id": chat_id,
            "reply_text": f"打开 Karma 操作台：\n{miniapp_url()}",
            "miniapp_url": miniapp_url(),
        })

    # 重新绑定 / 切换账户
    if text in {"重新绑定", "切换账户", "换绑"}:
        result = concierge.start_bind(tg_user_id)
        result.setdefault("chat_id", chat_id)
        result.setdefault("telegram_user_id", from_user.get("id"))
        return _deliver_reply(result)

    # Reply Keyboard 菜单按钮文本路由（输入框左侧菜单栏）
    if text in concierge.MENU_TEXTS:
        section = concierge.MENU_TEXTS[text]
        _MENU_FN = {
            "sync": concierge.menu_sync,
            "receipts": concierge.menu_receipts,
            "payments": concierge.menu_payments,
            "ongoing": concierge.menu_ongoing,
            "disputes": concierge.menu_disputes,
            "points": concierge.menu_points,
            "invite": concierge.menu_invite,
        }
        result = _MENU_FN[section](tg_user_id)
        result.setdefault("chat_id", chat_id)
        result.setdefault("telegram_user_id", from_user.get("id"))
        return _deliver_reply(result)

    # 2FA 绑定等待状态：接收「主身份ID 2FA码」
    if text and not text.startswith("/") and concierge.is_bind_pending(tg_user_id):
        if text in {"取消", "cancel", "退出"}:
            result = concierge.cancel_bind(tg_user_id)
        else:
            result = concierge.handle_bind_input(
                tg_user_id, text, username=from_user.get("username")
            )
        result.setdefault("chat_id", chat_id)
        result.setdefault("telegram_user_id", from_user.get("id"))
        return _deliver_reply(result)

    # 自然语言需求 → 对话编排层（意图解析 + 商家推荐）
    if text and not text.startswith("/"):
        result = concierge.recommend(tg_user_id, text)
        result.setdefault("chat_id", chat_id)
        result.setdefault("telegram_user_id", from_user.get("id"))
        return _deliver_reply(result)

    return _deliver_reply({
        "ok": True,
        "action": "noop",
        "chat_id": chat_id,
        "reply_text": "发送 /start 打开主菜单，或直接告诉我你的需求。",
    })
