"""Bot 对话编排层（concierge）。

产品交互铁律（2026-08-25 与负责人确认）：
1. 认证/绑钱包/授权额度只在官方操作台完成——聊天渠道内零认证零签名，杜绝钓鱼链接。
2. TG/WA 上用户只需直接说需求；Bot 后端直读操作台的认证信息与授权额度。
3. 先账单后结算：任何锁仓动作前必须出「账单确认卡」，用户点确认才动钱；
   agent 做错了有回旋余地——用户先看到为什么付、付给谁、付多少。
4. 授权额度内的支付由 Bot 后端自动完成 policy 检查与锁仓（无需用户再签名）。
5. 双边锁仓：用户锁资金托管，商家接单即承担履约责任，做错付出真金白银代价。

流程：说需求 → 推荐 TOP 商家（inline）→ 点选出账单确认卡 → 确认支付 →
额度内自动锁仓 → 商家收「接单」按钮推送 → 履约全程状态推送 → 验收放款。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from services.identity_gateway import store as identity_store
from services.miniapp_commerce import intent_discovery, orders, pipeline
from services.miniapp_registry import store as registry
from services.miniapp_trust import reputation as rep_svc

logger = logging.getLogger(__name__)

MAX_RECOMMEND = 3
PENDING_TTL_SECONDS = 600

# telegram_user_id -> {"intent": ..., "offers": [...], "ts": ...}
_PENDING: dict[int, dict[str, Any]] = {}

# 等待输入「主身份ID + 2FA码」的绑定状态：tg_id -> ts
_BIND_PENDING: dict[int, float] = {}

# ── Reply Keyboard 菜单栏（输入框左侧常驻） ─────────────────
MENU_KEYBOARD = {
    "keyboard": [
        [{"text": "🔗 同步认证"}, {"text": "📥 收款明细"}],
        [{"text": "📤 付款订单"}, {"text": "⏳ 进行中订单"}],
        [{"text": "⚖️ 争议订单"}, {"text": "🌟 我的积分"}],
        [{"text": "👥 邀请码&下级"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

# 菜单按钮文本 → 处理函数名（bot.py 文本路由用）
MENU_TEXTS = {
    "🔗 同步认证": "sync",
    "📥 收款明细": "receipts",
    "📤 付款订单": "payments",
    "⏳ 进行中订单": "ongoing",
    "⚖️ 争议订单": "disputes",
    "🌟 我的积分": "points",
    "👥 邀请码&下级": "invite",
}

# 已消耗状态（锁仓及之后都算占用额度）
_SPENT_STATUSES = {"LOCKED", "EXECUTED", "EVIDENCE_SUBMITTED", "VERIFIED", "SETTLED"}


def _send_message(chat_id: int | str, text: str, reply_markup: dict | None = None) -> None:
    from services.telegram.bot import send_message  # 延迟导入避免环

    try:
        send_message(chat_id, text, reply_markup=reply_markup)
    except Exception as exc:  # noqa: BLE001 — 推送失败不能影响主流程
        logger.warning("concierge_send_failed: %s", exc)


def _miniapp_url() -> str:
    from services.telegram.bot import miniapp_url as _url

    return _url()


def _prune_pending() -> None:
    now = time.time()
    for uid in [u for u, v in _PENDING.items() if now - v["ts"] > PENDING_TTL_SECONDS]:
        _PENDING.pop(uid, None)


def _policy_of(ident) -> dict[str, Any]:
    """操作台设置的授权额度（payment_policy）；缺省兜底。"""
    if ident and getattr(ident, "payment_policy", None):
        return ident.payment_policy
    return {"single_limit_usdc": "500", "daily_limit_usdc": "2000"}


def _spent_today_usdc(identity_id: str) -> float:
    """当日已锁仓占用额度（含已结算，不含退款）。"""
    day_start = int(time.time()) // 86400 * 86400
    total = 0.0
    for o in orders.list_orders_for_identity(identity_id):
        if (
            o.buyer_identity_id == identity_id
            and o.updated_at >= day_start
            and o.status.value in _SPENT_STATUSES
        ):
            total += float(o.amount_usdc or 0)
    return total


def _wallet_tail(ident) -> str:
    w = getattr(ident, "wallet", None) or ""
    return ("…" + w[-6:]) if w.startswith("0x") else (w or "未绑定")


def _auth_summary(ident) -> str:
    """认证与授权摘要——证明 Bot 已直读操作台数据，用户无需在聊天里做任何认证。"""
    pol = _policy_of(ident)
    single = float(pol.get("single_limit_usdc") or 0)
    daily = float(pol.get("daily_limit_usdc") or 0)
    spent = _spent_today_usdc(ident.identity_id)
    remain = max(daily - spent, 0.0)
    return (
        f"🛡 已认证 · 钱包 {_wallet_tail(ident)}\n"
        f"💳 授权额度：单笔 ≤{single:g}U · 今日剩余 {remain:g}U"
    )


def _catalog_with_reputation() -> list[dict[str, Any]]:
    """注册中心目录 + 真实成交声誉合并，供 rank_offers 使用。"""
    registry.seed_demo_if_empty()
    catalog = registry.offers_as_discovery_catalog()
    for item in catalog:
        seller = item.get("seller_identity_id")
        if not seller:
            continue
        try:
            rep = rep_svc.reputation_of(seller)
        except Exception:  # noqa: BLE001
            continue
        item["reputation_score"] = rep.get("reputation_score", item.get("reputation_score") or 50)
        item["settled_count"] = rep.get("settled_count", item.get("settled_count") or 0)
    return catalog


def recommend(telegram_user_id: int, text: str) -> dict[str, Any]:
    """处理用户自然语言需求：解析意图 + 推荐 TOP 商家（带 inline 选择按钮）。"""
    _prune_pending()
    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    if not ident:
        return _need_identity_reply(telegram_user_id)

    try:
        intent = intent_discovery.parse_chat_intent(text)
    except ValueError:
        return {"ok": True, "action": "intent_unparsed", "reply_text": "没看懂需求，请说清楚内容和预算，例如：我要买数据抓取服务，预算 100 USDC"}

    ranked = intent_discovery.rank_offers(intent, _catalog_with_reputation())
    if not ranked:
        return {
            "ok": True,
            "action": "no_match",
            "reply_text": f"暂无匹配「{intent.get('scene_id') or '相关'}」场景的商家上架，请稍后再试或换个说法。",
        }

    top = ranked[:MAX_RECOMMEND]
    _PENDING[int(telegram_user_id)] = {"intent": intent, "offers": top, "ts": time.time()}

    lines = [
        _auth_summary(ident),
        "",
        f"需求已理解：场景 {intent.get('scene_id') or '-'} · 预算 {intent.get('amount_usdc') or '-'} USDC",
        "",
        f"为你筛选出 {len(top)} 个优质商家：",
    ]
    buttons = []
    for i, o in enumerate(top, 1):
        rep = rep_svc.reputation_of(str(o.get("seller_identity_id") or "")).get("reputation_score", 50)
        settled = rep_svc.reputation_of(str(o.get("seller_identity_id") or "")).get("settled_count", 0)
        lines.append(f"{i}. {o.get('title')} — {o.get('amount_usdc')} USDC · 信誉 {rep:g} · 已成交 {settled} 单")
        buttons.append([{
            "text": f"{i}. {str(o.get('title'))[:24]} · {o.get('amount_usdc')}U",
            "callback_data": f"karma_pick:{o.get('offer_id')}",
        }])
    lines.append("")
    lines.append("点选商家后先出账单，你确认了才锁仓。")
    return {
        "ok": True,
        "action": "recommend",
        "reply_text": "\n".join(lines),
        "reply_markup": {"inline_keyboard": buttons},
    }


def handle_pick(telegram_user_id: int, offer_id: str) -> dict[str, Any]:
    """用户点选商家：出「账单确认卡」（先账单后结算，此时不动钱）。"""
    _prune_pending()
    pending = _PENDING.get(int(telegram_user_id))
    if not pending:
        return {"ok": True, "action": "expired", "reply_text": "推荐已过期，请重新发送你的需求。"}

    offer = next((o for o in pending["offers"] if o.get("offer_id") == offer_id), None)
    if not offer:
        return {"ok": True, "action": "offer_mismatch", "reply_text": "该商家不在本次推荐中，请重新发送需求。"}

    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    if not ident:
        _BIND_PENDING[int(telegram_user_id)] = time.time()
        return {"ok": True, "action": "need_identity", "reply_text": "身份绑定已失效。请重新发送：主身份ID 2FA安全码 完成同步。", "reply_markup": MENU_KEYBOARD}

    rep = rep_svc.reputation_of(str(offer.get("seller_identity_id") or "")).get("reputation_score", 50)
    settled = rep_svc.reputation_of(str(offer.get("seller_identity_id") or "")).get("settled_count", 0)

    amount = float(offer.get("amount_usdc") or pending["intent"].get("amount_usdc") or 0)
    pol = _policy_of(ident)
    single = float(pol.get("single_limit_usdc") or 0)
    daily = float(pol.get("daily_limit_usdc") or 0)
    spent = _spent_today_usdc(ident.identity_id)
    remain = max(daily - spent, 0.0)

    if amount <= single and spent + amount <= daily:
        quota_line = f"✅ 额度检查通过：在你的操作台授权额度内（单笔上限 {single:g}U · 今日剩余 {remain:g}U）"
    else:
        quota_line = (
            f"⚠️ 超出操作台授权额度（单笔上限 {single:g}U · 今日剩余 {remain:g}U），"
            "确认支付将被风控拒绝。请到操作台调整额度或换低价商品。"
        )

    lines = [
        "📋 账单确认（先看账单，你确认了才动钱）",
        "────────────────",
        f"商品：{offer.get('title')}",
        f"商家信誉 {rep:g} 分 · 已成交 {settled} 单",
        f"金额：{amount:g} USDC",
        f"付款钱包：{_wallet_tail(ident)}",
        "资金保障：锁定托管，商家交付验收通过才放款；货不对板可开争议退款",
        quota_line,
        "────────────────",
        "确认后自动完成：创建订单 → 锁定资金 → 商家接单 → 全程推送进度",
    ]
    buttons = [{
        "text": f"✅ 确认支付 {amount:g}U（锁仓托管）",
        "callback_data": f"karma_confirm:{offer_id}",
    }, {
        "text": "❌ 取消",
        "callback_data": "karma_cancel",
    }]
    return {
        "ok": True,
        "action": "bill_confirm",
        "reply_text": "\n".join(lines),
        "reply_markup": {"inline_keyboard": [buttons]},
    }


def handle_confirm(telegram_user_id: int, offer_id: str) -> dict[str, Any]:
    """用户确认支付：创建订单+账单，授权额度内由后端自动完成 policy 检查与锁仓。"""
    _prune_pending()
    pending = _PENDING.get(int(telegram_user_id))
    if not pending:
        return {"ok": True, "action": "expired", "reply_text": "账单已过期，请重新发送你的需求。"}

    offer = next((o for o in pending["offers"] if o.get("offer_id") == offer_id), None)
    if not offer:
        return {"ok": True, "action": "offer_mismatch", "reply_text": "该商家不在本次推荐中，请重新发送需求。"}

    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    if not ident:
        _BIND_PENDING[int(telegram_user_id)] = time.time()
        return {"ok": True, "action": "need_identity", "reply_text": "身份绑定已失效。请重新发送：主身份ID 2FA安全码 完成同步。", "reply_markup": MENU_KEYBOARD}

    order = orders.create_order(
        buyer_identity_id=ident.identity_id,
        intent=pending["intent"],
        buyer_wallet=ident.wallet,
        builder_address=offer.get("builder_address"),
    )
    orders.attach_offer(
        order.order_id,
        offer,
        seller_identity_id=str(offer.get("seller_identity_id") or "kid_unknown_seller"),
        seller_wallet=offer.get("seller_wallet"),
    )
    order = orders.get_order(order.order_id)
    pipeline.create_bill(
        order_id=order.order_id,
        buyer_wallet=order.buyer_wallet,
        seller_wallet=order.seller_wallet,
        amount_usdc=order.amount_usdc,
    )

    # 授权额度内自动锁仓（操作台预授权 → 聊天内无需签名）
    pol = _policy_of(ident)
    policy = {**pol, "spent_today_usdc": str(_spent_today_usdc(ident.identity_id))}
    try:
        orders.apply_policy(order.order_id, policy)
        order = orders.mark_locked(order.order_id, binding_id=None)
    except PermissionError as exc:
        orders.mark_refunded(order.order_id)
        pipeline.update_bill(order.order_id, status="rejected")
        _PENDING.pop(int(telegram_user_id), None)
        return {
            "ok": True,
            "action": "quota_rejected",
            "reply_text": (
                f"❌ 已拒绝（超出操作台授权额度）：{exc}\n"
                "如需支付，请到操作台调整授权额度后再试。\n" + _miniapp_url()
            ),
        }
    except ValueError as exc:
        return {"ok": True, "action": "lock_failed", "reply_text": f"锁仓失败：{exc}，资金未动，请重试。"}

    try:
        pipeline.update_bill(order.order_id, status="locked")
    except KeyError:
        pass
    _PENDING.pop(int(telegram_user_id), None)

    reply = (
        f"✅ 订单已创建：{order.order_id}\n"
        f"💰 {order.amount_usdc} USDC 已锁定托管（授权额度内自动完成，无需签名）\n"
        f"📦 当前进度：{orders.fulfillment_label(order)}\n"
        "商家接单后我会持续推送进度；交付验收通过才放款。"
    )

    # 通知商家：新订单 + 一键接单按钮
    seller_ident = (
        identity_store.get_by_id(order.seller_identity_id)
        if order.seller_identity_id and order.seller_identity_id != "kid_unknown_seller"
        else None
    )
    if seller_ident and seller_ident.telegram_user_id:
        _send_message(
            seller_ident.telegram_user_id,
            (
                f"🔔 新订单 {order.order_id}\n"
                f"商品：{offer.get('title')} · 金额 {order.amount_usdc} USDC\n"
                "买家资金已锁仓托管，接单即可开始履约。"
            ),
            reply_markup={"inline_keyboard": [[{
                "text": "📦 接单",
                "callback_data": f"karma_accept:{order.order_id}",
            }]]},
        )
    return {"ok": True, "action": "order_created", "order_id": order.order_id, "reply_text": reply}


def handle_cancel(telegram_user_id: int) -> dict[str, Any]:
    """用户点取消：作废本次推荐，未创建任何订单、未动任何资金。"""
    _PENDING.pop(int(telegram_user_id), None)
    return {"ok": True, "action": "cancelled", "reply_text": "已取消，没有创建订单、没有动钱。随时再说需求。"}


def handle_accept(telegram_user_id: int, order_id: str) -> dict[str, Any]:
    """商家在 TG 内一键接单。"""
    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    order = orders.get_order(order_id)
    if not order:
        return {"ok": True, "action": "order_not_found", "reply_text": "订单不存在或已失效。"}
    if not ident or ident.identity_id != order.seller_identity_id:
        return {"ok": True, "action": "not_seller", "reply_text": "你不是该订单的商家，无法接单。"}
    try:
        order = orders.accept_order(order_id)
    except ValueError as exc:
        return {"ok": True, "action": "accept_failed", "reply_text": f"接单失败：{exc}"}

    # 推送给买家：商家已接单
    buyer_ident = identity_store.get_by_id(order.buyer_identity_id)
    if buyer_ident and buyer_ident.telegram_user_id:
        _send_message(
            buyer_ident.telegram_user_id,
            (
                f"📦 订单 {order.order_id}：商家已接单（{orders.fulfillment_label(order)}）\n"
                "商家开始处理后我会继续推送，交付验收通过后自动放款。"
            ),
        )
    return {
        "ok": True,
        "action": "accepted",
        "reply_text": f"✅ 已接单：{order.order_id}（{orders.fulfillment_label(order)}）。开始处理请到商家端操作。",
    }


# ── 主菜单按钮布局 ──────────────────────────────────────────

MAIN_MENU_KEYBOARD = {"inline_keyboard": [
    [{"text": "🔗 同步认证账户", "callback_data": "karma_menu:sync"}],
    [{"text": "📥 收款明细", "callback_data": "karma_menu:receipts"},
     {"text": "📤 付款订单", "callback_data": "karma_menu:payments"}],
    [{"text": "⏳ 进行中订单", "callback_data": "karma_menu:ongoing"},
     {"text": "⚖️ 争议订单", "callback_data": "karma_menu:disputes"}],
    [{"text": "🌟 我的积分", "callback_data": "karma_menu:points"},
     {"text": "👥 邀请码&下级", "callback_data": "karma_menu:invite"}],
]}


def _need_identity_reply(telegram_user_id: int | None = None) -> dict[str, Any]:
    """未认证 → 引导 2FA 快速绑定（不再需要离开对话）。"""
    reply = {
        "ok": True,
        "action": "need_identity",
        "reply_text": (
            "🔐 你还没绑定 Karma 认证账户。\n\n"
            "绑定方式（在本对话直接完成）：\n"
            "发送：主身份ID + 2FA安全码\n"
            "例如：kid_xxxx 123456\n\n"
            "或到官方操作台查看你的认证信息：\n"
            f"{_miniapp_url()}\n\n"
            "💡 绑定后即可使用左侧菜单全部功能，聊天内零签名零密码。"
        ),
        "reply_markup": MENU_KEYBOARD,
    }
    if telegram_user_id:
        _BIND_PENDING[int(telegram_user_id)] = time.time()
        reply["action"] = "bind_prompt"
    return reply


def start_bind(telegram_user_id: int) -> dict[str, Any]:
    """引导用户输入 主身份ID + 2FA码。"""
    _BIND_PENDING[int(telegram_user_id)] = time.time()
    return {
        "ok": True,
        "action": "bind_prompt",
        "reply_text": (
            "🔗 同步 Karma 认证账户\n"
            "────────────────\n"
            "请发送：主身份ID 2FA安全码\n"
            "例如：kid_xxxx 123456\n\n"
            "（身份ID与2FA码在官网操作台的「账户安全」中查看；发送 取消 可退出）"
        ),
        "reply_markup": MENU_KEYBOARD,
    }


def handle_bind_input(telegram_user_id: int, text: str, *, username: str | None = None) -> dict[str, Any]:
    """处理「主身份ID 2FA码」输入，完成绑定。"""
    parts = text.split()
    if len(parts) == 2:
        identity_id, code = parts[0].strip(), parts[1].strip()
        try:
            ident = identity_store.bind_by_2fa(int(telegram_user_id), identity_id, code, username=username)
        except KeyError:
            return {
                "ok": True,
                "action": "bind_failed",
                "reply_text": f"❌ 身份ID不存在：{identity_id}\n请检查后重新发送，或发送 取消 退出。",
            }
        except ValueError as exc:
            return {
                "ok": True,
                "action": "bind_failed",
                "reply_text": f"❌ {exc}\n请重新发送，或发送 取消 退出。",
            }
        _BIND_PENDING.pop(int(telegram_user_id), None)
        return {
            "ok": True,
            "action": "bind_success",
            "identity_id": ident.identity_id,
            "reply_text": (
                "✅ 认证成功\n"
                "2FA 安全码已焚毁。左侧菜单已解锁，可直接说需求（如：帮我找个数据抓取服务，预算20U）。"
            ),
            "reply_markup": MENU_KEYBOARD,
        }
    return {
        "ok": True,
        "action": "bind_format_error",
        "reply_text": "格式不对哦。请发送：主身份ID 2FA安全码\n例如：kid_xxxx 123456\n（或发送 取消 退出）",
    }


def cancel_bind(telegram_user_id: int) -> dict[str, Any]:
    _BIND_PENDING.pop(int(telegram_user_id), None)
    return {"ok": True, "action": "bind_cancelled", "reply_text": "已取消绑定。可直接说需求，或点左侧菜单。"}


def is_bind_pending(telegram_user_id: int) -> bool:
    ts = _BIND_PENDING.get(int(telegram_user_id))
    if ts is None:
        return False
    if time.time() - ts > PENDING_TTL_SECONDS:
        _BIND_PENDING.pop(int(telegram_user_id), None)
        return False
    return True


def clear_bind_pending(telegram_user_id: int) -> None:
    """其他渠道（操作台 /v1/telegram/bind）绑定成功后清除聊天侧等待绑定状态。"""
    _BIND_PENDING.pop(int(telegram_user_id), None)


def _order_line(o, role: str) -> str:
    """单行订单摘要。"""
    title = "-"
    if o.offer and isinstance(o.offer, dict):
        title = str(o.offer.get("title") or "-")[:20]
    arrow = "→" if role == "buyer" else "←"
    return f"{arrow} {o.order_id[:14]}… | {title} | {o.amount_usdc}U | {orders.fulfillment_label(o)}"


def menu_main(telegram_user_id: int) -> dict[str, Any]:
    """主菜单入口——/start 或 /menu。"""
    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    if not ident:
        return _need_identity_reply(telegram_user_id)

    header = _auth_summary(ident)
    subs = identity_store.get_sub_identities(ident.identity_id)
    sub_note = ""
    if subs:
        sub_note = f"\n📎 已绑 {len(subs)} 个子身份（消费走主账户）"

    return {
        "ok": True,
        "action": "menu_main",
        "reply_text": f"{header}{sub_note}\n\n选择左侧菜单或直接说需求：",
        "reply_markup": MENU_KEYBOARD,
    }


def menu_sync(telegram_user_id: int) -> dict[str, Any]:
    """① 同步官网认证账户——展示当前认证状态、钱包、额度、子身份。"""
    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    if not ident:
        return _need_identity_reply(telegram_user_id)

    pol = _policy_of(ident)
    single = float(pol.get("single_limit_usdc") or 0)
    daily = float(pol.get("daily_limit_usdc") or 0)
    spent = _spent_today_usdc(ident.identity_id)

    lines = [
        "🔗 认证账户同步",
        "────────────────",
        f"身份ID：{ident.identity_id}",
        f"状态：{ident.status}",
        f"钱包：{_wallet_tail(ident)}",
        f"单笔额度：{single:g}U | 今日额度：{daily:g}U | 已用：{spent:g}U",
    ]
    subs = identity_store.get_sub_identities(ident.identity_id)
    if subs:
        lines.append(f"子身份：{len(subs)} 个")
        for s in subs:
            lines.append(f"  · {s.identity_id[:14]}… → {_wallet_tail(s)}")
    else:
        lines.append("子身份：未创建（到操作台生成）")
    lines += [
        "────────────────",
        "✅ 已同步。Bot 后端直读操作台数据，聊天内无需再认证。",
        "直接发需求即可，如「帮我找数据抓取商家，预算 100U」",
        "🔄 换绑账户：发送「重新绑定」",
    ]
    return {
        "ok": True,
        "action": "menu_sync",
        "reply_text": "\n".join(lines),
        "reply_markup": {"inline_keyboard": [[
            {"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"},
        ]]},
    }


def menu_receipts(telegram_user_id: int) -> dict[str, Any]:
    """② 收款明细——我是卖家的订单列表。"""
    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    if not ident:
        return _need_identity_reply(telegram_user_id)

    seller_orders = orders.orders_as_seller(ident.identity_id)
    if not seller_orders:
        return {
            "ok": True,
            "action": "menu_receipts",
            "reply_text": "📥 收款明细\n\n暂无收款记录。当有买家下单并锁仓后，这里会显示。",
            "reply_markup": {"inline_keyboard": [[
                {"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"},
            ]]},
        }

    lines = ["📥 收款明细", "────────────────"]
    buttons = []
    total_received = sum(float(o.amount_usdc or 0) for o in seller_orders if o.status.value == "SETTLED")
    lines.append(f"已结算收入：{total_received:g}U | 总订单：{len(seller_orders)} 单")
    lines.append("────────────────")
    for o in seller_orders[:10]:
        title = "-"
        if o.offer and isinstance(o.offer, dict):
            title = str(o.offer.get("title") or "-")[:18]
        lines.append(f"← {o.order_id[:14]}… | {title} | {o.amount_usdc}U | {orders.fulfillment_label(o)}")
        buttons.append([{
            "text": f"详情 {o.order_id[:14]}…",
            "callback_data": f"karma_detail:{o.order_id}",
        }])
    buttons.append([{"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"}])
    return {
        "ok": True,
        "action": "menu_receipts",
        "reply_text": "\n".join(lines),
        "reply_markup": {"inline_keyboard": buttons},
    }


def menu_payments(telegram_user_id: int) -> dict[str, Any]:
    """③ 付款订单——我是买家的订单列表。"""
    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    if not ident:
        return _need_identity_reply(telegram_user_id)

    buyer_orders = orders.orders_as_buyer(ident.identity_id)
    if not buyer_orders:
        return {
            "ok": True,
            "action": "menu_payments",
            "reply_text": "📤 付款订单\n\n暂无付款记录。下单购买服务后，这里会显示。",
            "reply_markup": {"inline_keyboard": [[
                {"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"},
            ]]},
        }

    lines = ["📤 付款订单", "────────────────"]
    buttons = []
    total_paid = sum(float(o.amount_usdc or 0) for o in buyer_orders if o.status.value == "SETTLED")
    lines.append(f"已结算支出：{total_paid:g}U | 总订单：{len(buyer_orders)} 单")
    lines.append("────────────────")
    for o in buyer_orders[:10]:
        title = "-"
        if o.offer and isinstance(o.offer, dict):
            title = str(o.offer.get("title") or "-")[:18]
        lines.append(f"→ {o.order_id[:14]}… | {title} | {o.amount_usdc}U | {orders.fulfillment_label(o)}")
        buttons.append([{
            "text": f"详情 {o.order_id[:14]}…",
            "callback_data": f"karma_detail:{o.order_id}",
        }])
    buttons.append([{"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"}])
    return {
        "ok": True,
        "action": "menu_payments",
        "reply_text": "\n".join(lines),
        "reply_markup": {"inline_keyboard": buttons},
    }


def menu_ongoing(telegram_user_id: int) -> dict[str, Any]:
    """④ 正在进行的订单。"""
    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    if not ident:
        return _need_identity_reply(telegram_user_id)

    ongoing = orders.orders_in_progress(ident.identity_id)
    if not ongoing:
        return {
            "ok": True,
            "action": "menu_ongoing",
            "reply_text": "⏳ 进行中订单\n\n暂无进行中的订单。",
            "reply_markup": {"inline_keyboard": [[
                {"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"},
            ]]},
        }

    lines = ["⏳ 进行中订单", "────────────────"]
    buttons = []
    for o in ongoing[:10]:
        role = "买家" if o.buyer_identity_id == ident.identity_id else "卖家"
        title = "-"
        if o.offer and isinstance(o.offer, dict):
            title = str(o.offer.get("title") or "-")[:18]
        lines.append(f"[{role}] {o.order_id[:14]}… | {title} | {o.amount_usdc}U | {orders.fulfillment_label(o)}")
        buttons.append([{
            "text": f"详情 {o.order_id[:14]}…",
            "callback_data": f"karma_detail:{o.order_id}",
        }])
    buttons.append([{"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"}])
    return {
        "ok": True,
        "action": "menu_ongoing",
        "reply_text": "\n".join(lines),
        "reply_markup": {"inline_keyboard": buttons},
    }


def menu_disputes(telegram_user_id: int) -> dict[str, Any]:
    """⑤ 仲裁争议订单。"""
    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    if not ident:
        return _need_identity_reply(telegram_user_id)

    disputed = orders.orders_in_dispute(ident.identity_id)
    if not disputed:
        return {
            "ok": True,
            "action": "menu_disputes",
            "reply_text": "⚖️ 争议订单\n\n暂无争议订单。如遇到问题可对锁仓订单发起争议。",
            "reply_markup": {"inline_keyboard": [[
                {"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"},
            ]]},
        }

    lines = ["⚖️ 争议订单", "────────────────"]
    buttons = []
    for o in disputed[:10]:
        role = "买家" if o.buyer_identity_id == ident.identity_id else "卖家"
        lines.append(f"[{role}] {o.order_id[:14]}… | {o.amount_usdc}U | {o.status.value}")
        buttons.append([{
            "text": f"详情 {o.order_id[:14]}…",
            "callback_data": f"karma_detail:{o.order_id}",
        }])
    buttons.append([{"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"}])
    return {
        "ok": True,
        "action": "menu_disputes",
        "reply_text": "\n".join(lines),
        "reply_markup": {"inline_keyboard": buttons},
    }


def menu_points(telegram_user_id: int) -> dict[str, Any]:
    """⑥ 我的积分详情。"""
    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    if not ident:
        return _need_identity_reply(telegram_user_id)

    rep = rep_svc.reputation_of(ident.identity_id)
    settled_count = rep.get("settled_count", 0)
    rep_score = rep.get("reputation_score", 50)

    lines = [
        "🌟 我的积分",
        "────────────────",
        f"Karma 积分：{ident.karma_points:g}",
        f"信誉评分：{rep_score:g}",
        f"已成交单数：{settled_count}",
        f"身份等级：{'金牌商家' if rep_score >= 80 else '银牌' if rep_score >= 60 else '认证用户'}",
        "────────────────",
        "积分获取：每笔成功结算 +10 积分 | 邀请好友首次交易 +50 积分",
    ]
    return {
        "ok": True,
        "action": "menu_points",
        "reply_text": "\n".join(lines),
        "reply_markup": {"inline_keyboard": [[
            {"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"},
        ]]},
    }


def menu_invite(telegram_user_id: int) -> dict[str, Any]:
    """⑦ 专属邀请码与下级详情。"""
    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    if not ident:
        return _need_identity_reply(telegram_user_id)

    referrals = identity_store.get_referral_chain(ident.identity_id)

    lines = [
        "👥 邀请码 & 下级",
        "────────────────",
        f"我的邀请码：{ident.invite_code}",
        f"已邀请人数：{len(referrals)}",
        f"邀请奖励积分：{len(referrals) * 50:g}",
        "────────────────",
    ]
    if referrals:
        lines.append("下级列表：")
        for r in referrals[:10]:
            lines.append(f"  · {_wallet_tail(r)} | 积分 {r.karma_points:g} | {r.status}")
    else:
        lines.append("暂无下级。分享你的邀请码，好友首次交易你获 50 积分。")
    lines.append("")
    share_link = f"https://t.me/hookkarma_bot?start=ref_{ident.invite_code}"
    lines.append(f"分享链接：{share_link}")
    return {
        "ok": True,
        "action": "menu_invite",
        "reply_text": "\n".join(lines),
        "reply_markup": {"inline_keyboard": [[
            {"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"},
        ]]},
    }


def menu_order_detail(telegram_user_id: int, order_id: str) -> dict[str, Any]:
    """订单详情——从菜单列表点入。"""
    ident = identity_store.resolve_effective_identity(int(telegram_user_id))
    if not ident:
        return _need_identity_reply(telegram_user_id)

    detail = orders.order_detail(order_id)
    if not detail:
        return {
            "ok": True,
            "action": "detail_not_found",
            "reply_text": "订单不存在或已失效。",
            "reply_markup": {"inline_keyboard": [[
                {"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"},
            ]]},
        }

    role = "买家" if detail["buyer_identity_id"] == ident.identity_id else "卖家"
    title = "-"
    if detail.get("offer") and isinstance(detail["offer"], dict):
        title = detail["offer"].get("title", "-")

    lines = [
        f"📋 订单详情 [{role}]",
        "────────────────",
        f"订单ID：{detail['order_id']}",
        f"商品：{title}",
        f"金额：{detail['amount_usdc']} USDC",
        f"状态：{detail['status']} | {detail['fulfillment_label']}",
        f"买家钱包：{detail.get('buyer_wallet', '-') or '-'}",
        f"卖家钱包：{detail.get('seller_wallet', '-') or '-'}",
        f"创建时间：{time.strftime('%Y-%m-%d %H:%M', time.localtime(detail['created_at']))}",
    ]
    if detail.get("evidence"):
        lines.append(f"交付凭证：已提交")
    if detail.get("policy_result"):
        lines.append(f"风控检查：已通过")
    lines += ["────────────────", "状态变更记录："]
    for h in detail.get("history", [])[-5:]:
        t = time.strftime("%m-%d %H:%M", time.localtime(h.get("at", 0)))
        lines.append(f"  · {t} {h.get('status')} {h.get('note', '')}")

    return {
        "ok": True,
        "action": "menu_detail",
        "reply_text": "\n".join(lines),
        "reply_markup": {"inline_keyboard": [[
            {"text": "⬅️ 返回主菜单", "callback_data": "karma_menu:main"},
        ]]},
    }


def handle_callback(callback_query: dict[str, Any]) -> dict[str, Any]:
    """处理 inline 按钮回调（karma_pick / karma_confirm / karma_cancel / karma_accept）。"""
    from_user = callback_query.get("from") or {}
    data = (callback_query.get("data") or "").strip()
    chat_id = (callback_query.get("message") or {}).get("chat", {}).get("id")

    # best-effort answerCallbackQuery 去掉客户端 loading 态
    try:
        from services.telegram.bot import bot_token, telegram_api_base

        import httpx

        with httpx.Client(timeout=5.0) as client:
            client.post(
                f"{telegram_api_base()}/bot{bot_token()}/answerCallbackQuery",
                json={"callback_query_id": callback_query.get("id")},
            )
    except Exception:  # noqa: BLE001
        pass

    uid = int(from_user.get("id") or 0)
    if data.startswith("karma_menu:"):
        section = data.split(":", 1)[1]
        _MENU_DISPATCH = {
            "main": menu_main,
            "sync": menu_sync,
            "receipts": menu_receipts,
            "payments": menu_payments,
            "ongoing": menu_ongoing,
            "disputes": menu_disputes,
            "points": menu_points,
            "invite": menu_invite,
        }
        handler = _MENU_DISPATCH.get(section, menu_main)
        result = handler(uid)
    elif data.startswith("karma_detail:"):
        result = menu_order_detail(uid, data.split(":", 1)[1])
    elif data.startswith("karma_pick:"):
        result = handle_pick(uid, data.split(":", 1)[1])
    elif data.startswith("karma_confirm:"):
        result = handle_confirm(uid, data.split(":", 1)[1])
    elif data == "karma_cancel":
        result = handle_cancel(uid)
    elif data.startswith("karma_accept:"):
        result = handle_accept(uid, data.split(":", 1)[1])
    else:
        result = {"ok": True, "action": "unknown_callback", "reply_text": "未知操作。"}
    result["chat_id"] = chat_id or from_user.get("id")
    return result


def notify_order_event(order_id: str, text: str, reply_markup: dict | None = None) -> None:
    """把订单事件推送给买卖双方（有 Telegram 绑定才发；失败静默不影响主流程）。"""
    order = orders.get_order(order_id)
    if not order:
        return
    ids = {order.buyer_identity_id, order.seller_identity_id} - {None, "kid_unknown_seller"}
    for iid in ids:
        ident = identity_store.get_by_id(iid)
        if ident and ident.telegram_user_id:
            _send_message(ident.telegram_user_id, text, reply_markup=reply_markup)
