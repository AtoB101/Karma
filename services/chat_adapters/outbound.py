"""出站消息：平台无关的 ``OutboundMessage`` + 两套渲染 + 统一发送。

发送前**一律**先过 ``guard``：拿掉控制字符、截断、并扫一遍疑似凭据。命中就抛错
拒发 —— 这条通道宁可少发一条，也不能把钥匙贴进聊天记录。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.chat_adapters import config, guard, whatsapp
from services.chat_adapters.events import SUPPORTED_PLATFORMS, TELEGRAM


@dataclass(frozen=True)
class OutboundMessage:
    """一条要发进聊天窗口的消息。

    ``buttons`` 是 ``(显示文字, 回传载荷)`` 对。载荷只走本适配器的命令面
    （目前仅 ``/connect``、``/help``），**不带**任何身份或授权语义。
    """

    text: str
    buttons: tuple[tuple[str, str], ...] = ()
    url: str | None = None
    url_label: str = "打开操作台"


def render_telegram_markup(message: OutboundMessage) -> dict[str, Any] | None:
    rows: list[list[dict[str, Any]]] = []
    for label, payload in message.buttons:
        rows.append([{"text": label, "callback_data": payload}])
    if message.url:
        rows.append([{"text": message.url_label, "url": message.url}])
    return {"inline_keyboard": rows} if rows else None


def render_whatsapp_buttons(message: OutboundMessage) -> tuple[tuple[str, str], ...]:
    """WhatsApp 只有「按钮」没有「链接按钮」，链接直接写进正文。"""
    return tuple(message.buttons)


def _body_text(message: OutboundMessage) -> str:
    text = guard.sanitize_text(message.text)
    if message.url and message.url not in text:
        text = f"{text}\n{message.url}"
    return guard.assert_no_secret(text)


def send(platform: str, chat_id: str, message: OutboundMessage) -> dict[str, Any]:
    """发一条消息；返回 ``{"sent": bool, ...}``。平台不认识就直接拒。"""
    if platform not in SUPPORTED_PLATFORMS:
        return {"sent": False, "ok": False, "error": f"unsupported platform: {platform}"}
    text = _body_text(message)
    if platform == TELEGRAM:
        return _send_telegram(chat_id, text, message)
    return _send_whatsapp(chat_id, text, message)


def _send_telegram(chat_id: str, text: str, message: OutboundMessage) -> dict[str, Any]:
    from services.telegram import bot as tg_bot  # 延迟导入：避免与既有模块互相牵动

    result: dict[str, Any] = {
        "ok": True,
        "action": "adapter_reply",
        "chat_id": chat_id,
        "reply_text": text,
        "reply_markup": render_telegram_markup(message),
    }
    return tg_bot.deliver_reply(result)


def _send_whatsapp(chat_id: str, text: str, message: OutboundMessage) -> dict[str, Any]:
    if not whatsapp.send_enabled():
        return {"ok": True, "sent": False, "send_skipped": "outbound send disabled for this environment"}
    if not whatsapp.send_configured():
        return {"ok": False, "sent": False, "error": "whatsapp send is not configured"}
    try:
        api_result = whatsapp.send_message(
            chat_id, text, buttons=render_whatsapp_buttons(message)
        )
    except Exception as exc:  # noqa: BLE001 - 发送失败不能把 webhook 带坏（平台会重投）
        return {"ok": False, "sent": False, "send_error": str(exc)}
    return {"ok": True, "sent": True, "send_result": api_result}


def pairing_links() -> dict[str, str]:
    """接入引导里用到的两个操作台地址。"""
    return {
        "pairing": config.console_pairing_url(),
        "agents": config.console_agents_url(),
    }