"""跨平台聊天适配器入口（S6）—— Telegram / WhatsApp。

挂载点：``/v1/adapters``（见 ``api/app.py``）。

三条红线写死在这里 —— 本文件是它们唯一可能被绕过的地方：

1. **不验签不放行**：Telegram 缺 ``TELEGRAM_WEBHOOK_SECRET`` → 403；
   WhatsApp 缺 ``WHATSAPP_APP_SECRET`` → 503、签名对不上 → 403。
   平台凭据没配就是没配，不「先放过来再说」。
2. **聊天账号不是资金凭证**：本路由没有任何一条路径能产生、扩大或动用资金权限。
   入站消息一律经 ``commands.decide``，只可能落到那几个白名单动作上。
3. **出站不泄漏**：所有要发出去的文本都过 ``guard``；``/notify`` 扫到疑似凭据直接 400。

和 Telegram MiniApp 那条 webhook（``/v1/telegram/bot/webhook``）的关系：**同一条** bot
只能挂一个 webhook，所以这里不是「再来一个」，而是**超集** —— 本适配器不认识的
update 原样交回 ``services.telegram.bot.handle_update``，既有 concierge 功能一条不少。
"""
from __future__ import annotations

import hmac
import json
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from services.chat_adapters import commands, config, events, guard, outbound, whatsapp
from services.chat_adapters.events import SUPPORTED_PLATFORMS

router = APIRouter()


class NotifyBody(BaseModel):
    """后端 / 运维把一条通知推给某个会话。"""

    platform: str = Field(min_length=1, max_length=32)
    chat_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=guard.MAX_OUTBOUND_CHARS)


@router.get("/status")
def adapter_status() -> dict[str, Any]:
    """通道健康视图：只回布尔与清单，绝不回显任何凭据。"""
    return {
        "platforms": list(SUPPORTED_PLATFORMS),
        "telegram": {"webhook_configured": bool((os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip())},
        "whatsapp": {
            "webhook_configured": whatsapp.webhook_configured(),
            "send_configured": whatsapp.send_configured(),
        },
        "notify_configured": bool(config.notify_token()),
    }


@router.get("/whatsapp/webhook")
def whatsapp_handshake(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    """Meta 订阅握手：token 对上才回 challenge。"""
    if not whatsapp.verify_token():
        raise HTTPException(503, "whatsapp webhook is not configured")
    challenge = whatsapp.check_hub_challenge(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        raise HTTPException(403, "invalid verify token")
    return PlainTextResponse(challenge)


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
):
    """WhatsApp 入站。验签用**原始字节**，所以必须先 `await request.body()`。"""
    if not whatsapp.webhook_configured():
        raise HTTPException(503, "whatsapp webhook is not configured")
    raw = await request.body()
    if not whatsapp.verify_signature(raw, x_hub_signature_256):
        raise HTTPException(403, "invalid signature")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "invalid json")

    handled = _dispatch_all(events.normalize_whatsapp(payload))
    return {"ok": True, "handled": len(handled)}


@router.post("/telegram/webhook")
async def telegram_webhook(
    body: dict,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """Telegram 入站。认识的命令本适配器答，其余原样交回既有 concierge。"""
    from services.telegram import bot as tg_bot

    if not tg_bot.verify_webhook_secret(x_telegram_bot_api_secret_token):
        raise HTTPException(403, "invalid webhook secret")

    inbound = events.normalize_telegram(body)
    if not inbound:
        return {"ok": True, "handled": "ignored"}

    event = inbound[0]
    decision = commands.decide(event)
    if decision.action == commands.ACTION_DELEGATE:
        return tg_bot.handle_update(body)
    if decision.reply is None:  # pragma: no cover - 白名单动作都有回复
        return {"ok": True, "handled": decision.action, "sent": False}
    result = outbound.send(event.platform, event.chat_id, decision.reply)
    return {"ok": True, "handled": decision.action, "sent": bool(result.get("sent"))}


@router.post("/notify")
def adapter_notify(
    body: NotifyBody,
    x_karma_adapter_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """服务侧推送：把一条通知发到某个聊天会话。静态 bearer，缺配一律 503。"""
    expected = config.notify_token()
    if not expected:
        raise HTTPException(503, "adapter notify channel is not configured")
    if not x_karma_adapter_token or not hmac.compare_digest(x_karma_adapter_token, expected):
        raise HTTPException(401, "invalid adapter token")
    if body.platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(400, "unsupported platform")
    try:
        guard.assert_no_secret(body.text)
    except guard.SecretLeakError:
        raise HTTPException(400, "refusing to send text that looks like a credential")
    result = outbound.send(
        body.platform, body.chat_id, outbound.OutboundMessage(text=body.text)
    )
    return {"ok": True, "sent": bool(result.get("sent"))}


def _dispatch_all(inbound: list[events.ChatEvent]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for event in inbound:
        decision = commands.decide(event)
        if decision.reply is None:
            continue
        results.append(outbound.send(event.platform, event.chat_id, decision.reply))
    return results