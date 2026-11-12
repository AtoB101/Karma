"""平台入站事件归一化：Telegram Update / WhatsApp Cloud API webhook → ``ChatEvent``。

两边报文形状完全不同（Telegram 是 ``message`` / ``callback_query``，WhatsApp 是
``entry[].changes[].value.messages[]``），但适配层只关心同一件事：谁、在哪个会话里、
说了什么或点了哪个按钮。差异收敛在这里，其余模块一律只认 ``ChatEvent``。

红线（本模块**不**做的事）：

- 不做任何鉴权判定。验签在 webhook 层完成；这里解析出的 ``sender_id`` **不是**
  「这个人已经通过 Karma 认证」的证据，**更不是**资金凭证。
- 不解析、也不保留任何凭据字段（平台入站报文里本来也不该有）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.chat_adapters.guard import sanitize_text

#: 入站文本上限（够覆盖 Telegram 4096 与 WhatsApp 4096）。
MAX_TEXT_CHARS = 4000
#: 会话 / 发送者标识上限，防超长注入。
MAX_ID_CHARS = 128
#: 按钮回传载荷上限。
MAX_PAYLOAD_CHARS = 256

TELEGRAM = "telegram"
WHATSAPP = "whatsapp"
SUPPORTED_PLATFORMS = (TELEGRAM, WHATSAPP)


@dataclass(frozen=True)
class ChatEvent:
    """一条归一化后的入站消息。

    ``sender_id`` 只代表「平台上的这个人」，**不代表**任何 Karma 身份或授权。
    """

    platform: str
    chat_id: str
    sender_id: str
    text: str = ""
    button_payload: str = ""
    message_id: str = ""

    @property
    def is_command(self) -> bool:
        return self.text.startswith("/")


def _ident(value: Any) -> str:
    return sanitize_text(value, limit=MAX_ID_CHARS)


def normalize_telegram(update: dict[str, Any]) -> list[ChatEvent]:
    """Telegram Update → ``ChatEvent``（不认识的 update 返回空列表）。"""
    if not isinstance(update, dict):
        return []

    callback = update.get("callback_query")
    if isinstance(callback, dict):
        message = callback.get("message") or {}
        chat = (message.get("chat") or {}) if isinstance(message, dict) else {}
        sender = callback.get("from") or {}
        chat_id = _ident(chat.get("id"))
        if not chat_id:
            return []
        return [
            ChatEvent(
                platform=TELEGRAM,
                chat_id=chat_id,
                sender_id=_ident((sender or {}).get("id")),
                button_payload=sanitize_text(callback.get("data"), limit=MAX_PAYLOAD_CHARS),
                message_id=_ident(callback.get("id")),
            )
        ]

    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return []
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = _ident(chat.get("id"))
    if not chat_id:
        return []
    return [
        ChatEvent(
            platform=TELEGRAM,
            chat_id=chat_id,
            sender_id=_ident((sender or {}).get("id")),
            text=sanitize_text(message.get("text"), limit=MAX_TEXT_CHARS),
            message_id=_ident(message.get("message_id")),
        )
    ]


def _whatsapp_text(message: dict[str, Any]) -> tuple[str, str]:
    """(text, button_payload)。"""
    body = (message.get("text") or {}).get("body")
    if body:
        return sanitize_text(body, limit=MAX_TEXT_CHARS), ""
    interactive = message.get("interactive") or {}
    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
    if reply:
        return "", sanitize_text(reply.get("id"), limit=MAX_PAYLOAD_CHARS)
    # 语音 / 图片 / 位置等非文本消息：给个空文本，交给命令面回默认提示。
    return "", ""


def normalize_whatsapp(payload: dict[str, Any]) -> list[ChatEvent]:
    """WhatsApp Cloud API webhook → ``ChatEvent``。

    1:1 会话里 WhatsApp 不给「chat」概念，``wa_id`` 就是会话标识；这里用它做
    ``chat_id`` 与 ``sender_id``（两者在 1:1 场景下本来就是同一个）。
    """
    if not isinstance(payload, dict):
        return []
    events: list[ChatEvent] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            value = (change or {}).get("value") or {}
            if not isinstance(value, dict):
                continue
            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                wa_id = _ident(message.get("from"))
                if not wa_id:
                    continue
                text, payload_id = _whatsapp_text(message)
                events.append(
                    ChatEvent(
                        platform=WHATSAPP,
                        chat_id=wa_id,
                        sender_id=wa_id,
                        text=text,
                        button_payload=payload_id,
                        message_id=_ident(message.get("id")),
                    )
                )
    return events