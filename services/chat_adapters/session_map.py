"""会话 ↔ Karma 身份 的解析（**只读**）。

本模块只回答一个问题：**给定一个 Karma 身份，它的聊天会话是哪一个？**

它只「读」既有关系，不创建绑定、不产生凭据、也不猜：

- 读的是用户已经在别处（MiniApp 认证 / 2FA）主动做过的 Telegram 绑定
  （``services.identity_gateway.store`` 里的 ``telegram_user_id``）。那是既有事实，
  适配器只**复用**，绝不新造一套绑定。
- 子身份一般没有自己的 TG 绑定（绑定属于人），所以沿 ``parent_identity_id``
  回溯到主身份。TG 绑定本身是 1:1 的（换绑会先解旧的），回溯不会串号。
- WhatsApp：树内**没有**「身份 ↔ wa_id」这种绑定，因此一律返回 ``None``。

拿不到会话号就返回 ``None`` —— fail-closed：宁可漏发一条通知，也不能发给别人。
"""
from __future__ import annotations

from services.chat_adapters.events import TELEGRAM


def resolve_chat_id(platform: str, karma_identity_id: str) -> str | None:
    """把 Karma 身份解析成聊天会话号；解析不到返回 ``None``。"""
    identity_id = (karma_identity_id or "").strip()
    if not identity_id:
        return None
    if platform != TELEGRAM:
        return None
    telegram_user_id = _telegram_user_id(identity_id)
    return str(telegram_user_id) if telegram_user_id else None


def _telegram_user_id(identity_id: str) -> int | None:
    """沿身份链读既有 TG 绑定（延迟导入，避免与身份库互相牵动）。"""
    from services.identity_gateway import store

    seen: set[str] = set()
    pending = [identity_id]
    while pending:
        current = pending.pop(0)
        if not current or current in seen:
            continue
        seen.add(current)
        ident = store.get_by_id(current)
        if not ident:
            continue
        if ident.telegram_user_id:
            return int(ident.telegram_user_id)
        if ident.parent_identity_id:
            pending.append(ident.parent_identity_id)
    return None
