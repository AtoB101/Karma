"""跨平台聊天适配器入口（S6）—— Telegram / WhatsApp。

挂载点：``/v1/adapters``（见 ``api/app.py``）。

三条红线写死在这里 —— 本文件是它们唯一可能被绕过的地方：

1. **先验签，再解析**。任何一个端点的第一件事都是验签 / 鉴权，报文解析排在其后：
   Telegram 缺 ``TELEGRAM_WEBHOOK_SECRET`` → 403；WhatsApp 缺 ``WHATSAPP_APP_SECRET``
   → 503、``X-Hub-Signature-256`` 对不上 → 403；``/notify`` 缺配 → 503、token 不对 → 401。
   顺序很要紧：解析放在验签前面，未认证的调用方就能从 422 的字段名里读出接口形状。
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

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, model_validator

from services.chat_adapters import commands, config, events, guard, notify, outbound, whatsapp
from services.chat_adapters.events import SUPPORTED_PLATFORMS

router = APIRouter()


class NotifyBody(BaseModel):
    """后端 / 运维把一条通知推给某个会话。

    投递目标**二选一**：

    - ``chat_id``：调用方已经知道会话号（平台原生 ID）。
    - ``karma_identity_id``：调用方只知道 Karma 身份 —— 由适配器解析出会话号，
      解析不到就不发（fail-closed）。后端因此不必持有、也不必传播会话号。
    """

    platform: str = Field(min_length=1, max_length=32)
    chat_id: str | None = Field(default=None, max_length=128)
    karma_identity_id: str | None = Field(default=None, max_length=128)
    text: str = Field(min_length=1, max_length=guard.MAX_OUTBOUND_CHARS)

    @model_validator(mode="after")
    def _exactly_one_target(self) -> NotifyBody:
        chat_id = (self.chat_id or "").strip()
        identity_id = (self.karma_identity_id or "").strip()
        if bool(chat_id) == bool(identity_id):
            raise ValueError("provide exactly one of chat_id / karma_identity_id")
        return self


def _require_notify_token(
    x_karma_adapter_token: str | None = Header(default=None),
) -> None:
    """``/notify`` 的静态 bearer。

    做成依赖而不是写在函数体里，是为了让它在 **body 校验之前** 跑：否则一个
    body 格式不对的未认证请求会先拿到 422（连字段名一起），等于免费读接口形状。
    """
    expected = config.notify_token()
    if not expected:
        raise HTTPException(503, "adapter notify channel is not configured")
    if not x_karma_adapter_token or not hmac.compare_digest(x_karma_adapter_token, expected):
        raise HTTPException(401, "invalid adapter token")


@router.get("/status")
def adapter_status() -> dict[str, Any]:
    """通道健康视图：只回布尔与清单，绝不回显任何凭据。"""
    return {
        "platforms": list(SUPPORTED_PLATFORMS),
        "telegram": {
            "webhook_configured": bool((os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip())
        },
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
    """WhatsApp 入站。验签用**原始字节**，所以先 `await request.body()` 再解析。"""
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
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """Telegram 入站。认识的命令本适配器答，其余原样交回既有 concierge。

    注意这里**不**把 body 声明成 pydantic 参数：那样 FastAPI 会先解析报文再进函数体，
    未验签的坏报文就会拿到 422。改成先验签、再自己解析，坏报文一律 400。
    """
    from services.telegram import bot as tg_bot

    if not tg_bot.verify_webhook_secret(x_telegram_bot_api_secret_token):
        raise HTTPException(403, "invalid webhook secret")
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        raise HTTPException(400, "invalid json")
    if not isinstance(body, dict):
        raise HTTPException(400, "invalid json")

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
    _auth: None = Depends(_require_notify_token),
) -> dict[str, Any]:
    """服务侧推送：把一条通知发到某个聊天会话。鉴权在 body 校验之前完成。"""
    if body.platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(400, "unsupported platform")

    chat_id = (body.chat_id or "").strip()
    if chat_id:
        # 调用方直接给了会话号：仍然先扫凭据，再发。
        try:
            guard.assert_no_secret(body.text)
        except guard.SecretLeakError:
            raise HTTPException(400, "refusing to send text that looks like a credential")
        result = outbound.send(
            body.platform, chat_id, outbound.OutboundMessage(text=body.text)
        )
        return {"ok": True, "sent": bool(result.get("sent"))}

    # 调用方只给了身份：由适配器解析会话号（解析不到就不发）。
    result = notify.notify_identity(
        (body.karma_identity_id or "").strip(), body.text, platform=body.platform
    )
    if result.get("reason") == "refused_secret":
        raise HTTPException(400, "refusing to send text that looks like a credential")
    return {"ok": True, "sent": bool(result.get("sent")), "reason": result.get("reason")}


def _dispatch_all(inbound: list[events.ChatEvent]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for event in inbound:
        decision = commands.decide(event)
        if decision.reply is None:
            continue
        results.append(outbound.send(event.platform, event.chat_id, decision.reply))
    return results