"""Telegram Bot webhook + deep-link helpers."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from services.telegram import bot as tg_bot

router = APIRouter()


class WebhookBody(BaseModel):
    update_id: int | None = None
    message: dict | None = None
    edited_message: dict | None = None


class DeepLinkBody(BaseModel):
    identity_id: str | None = None
    action: str = "bind"
    startapp: str | None = None


@router.post("/telegram/bot/webhook")
def telegram_bot_webhook(
    body: dict,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if not tg_bot.verify_webhook_secret(x_telegram_bot_api_secret_token):
        raise HTTPException(403, "invalid webhook secret")
    result = tg_bot.handle_update(body)
    return result


@router.get("/telegram/bot/deeplink")
def telegram_deeplink(identity_id: str | None = None, action: str = "bind"):
    return {
        "bot_start": tg_bot.deep_link_start(identity_id=identity_id, action=action),
        "miniapp": tg_bot.miniapp_deeplink(startapp=f"{action}_{identity_id}" if identity_id else action),
    }


@router.post("/telegram/bot/deeplink")
def telegram_deeplink_post(body: DeepLinkBody):
    return {
        "bot_start": tg_bot.deep_link_start(identity_id=body.identity_id, action=body.action),
        "miniapp": tg_bot.miniapp_deeplink(
            startapp=body.startapp or (f"{body.action}_{body.identity_id}" if body.identity_id else body.action)
        ),
    }
