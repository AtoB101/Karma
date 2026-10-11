"""按身份投递出站通知 —— 让后端不必知道会话号。

后端（身份 / 结算 / 争议）只知道「哪个人」（Karma 身份），不知道他在哪个聊天
窗口。本模块把身份解析成会话再投递；解析不到就**不发**。

立场与 ``services.console_notice`` 一致：通知是**旁路** —— 任何失败都返回结果
字典、绝不抛回调用方。一条通知发不出去，不该拖垮一笔真实交易。

红线：本模块只发消息。不创建绑定、不动钱、不产凭据、不代签。
"""
from __future__ import annotations

from typing import Any

from services.chat_adapters import guard, outbound, session_map
from services.chat_adapters.events import TELEGRAM


def send_notice(
    platform: str,
    chat_id: str,
    text: str,
    *,
    buttons: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    """给一个已知会话号发通知。返回 ``{"ok", "sent", "reason", ...}``，永不抛错。"""
    try:
        guard.assert_no_secret(text)
    except guard.SecretLeakError:
        return {"ok": False, "sent": False, "reason": "refused_secret"}
    try:
        result = outbound.send(
            platform, chat_id, outbound.OutboundMessage(text=text, buttons=buttons)
        )
    except Exception as exc:  # noqa: BLE001 - 通知是旁路，失败也要吞
        return {"ok": False, "sent": False, "reason": "send_failed", "error": str(exc)}
    if not isinstance(result, dict):
        return {"ok": False, "sent": False, "reason": "send_failed"}
    sent = bool(result.get("sent"))
    if sent:
        reason = "ok"
    else:
        reason = str(
            result.get("send_skipped") or result.get("error") or "not_sent"
        )
    return {"ok": bool(result.get("ok", True)), "sent": sent, "reason": reason}


def notify_identity(
    karma_identity_id: str,
    text: str,
    *,
    platform: str = TELEGRAM,
    buttons: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    """给一个 Karma 身份发通知：先解析会话，再投递。

    解析不到（身份不存在、没绑 TG、或平台是 WhatsApp）→ ``no_chat_binding``，
    绝不猜、绝不群发。凭据形态的文本**先于**解析就被拒 —— 这是卫生规则，
    跟有没有会话可发无关。
    """
    try:
        guard.assert_no_secret(text)
    except guard.SecretLeakError:
        return {"ok": False, "sent": False, "reason": "refused_secret"}
    chat_id = session_map.resolve_chat_id(platform, karma_identity_id)
    if not chat_id:
        return {"ok": False, "sent": False, "reason": "no_chat_binding"}
    result = send_notice(platform, chat_id, text, buttons=buttons)
    result["chat_id"] = guard.mask_chat_id(chat_id)
    return result
