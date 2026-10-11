"""命令面 —— 平台无关，且**故意做得很小**。

这条通道只干两件事：告诉用户「怎么把 agent 接进来」，以及把主人引到操作台。
它没有任何一条命令能花钱、能授权、能读别人的数据。

为什么故意不做更多：聊天窗口是**半可信**的（账号可能被接管、消息可能被转发），
任何在这里放行的动作，都等于把「聊天账号」升格成凭证 —— 那是红线（架构 §3）。
需要动钱或动权限的事，一律回操作台，由主人已认证的会话 + 钱包签名完成。

新增命令前先问一句：这个动作能不能只靠聊天账号就发生？能，就不要加。
"""
from __future__ import annotations

from dataclasses import dataclass

from services.chat_adapters import outbound
from services.chat_adapters.events import TELEGRAM, ChatEvent

ACTION_CONNECT = "connect"
ACTION_HELP = "help"
#: Telegram 侧：不是本适配器的命令，交给既有 concierge（保留原有全部功能）。
ACTION_DELEGATE = "delegate"
#: WhatsApp 侧：没有 concierge 可交，回一段默认提示。
ACTION_FALLBACK = "fallback"

#: 归一化后的触发词（都按小写比对）。
CONNECT_TRIGGERS = frozenset(
    {
        "/connect",
        "/karma",
        "/pair",
        "/接入",
        "接入",
        "接入karma",
        "接入 karma",
        "连接karma",
        "绑定karma",
    }
)
HELP_TRIGGERS = frozenset({"/help", "/帮助", "帮助", "/start_help"})

#: 命令面**允许**产生的动作白名单。用例直接拿它做「没有动钱入口」的断言。
ALLOWED_ACTIONS = frozenset({ACTION_CONNECT, ACTION_HELP, ACTION_DELEGATE, ACTION_FALLBACK})


@dataclass(frozen=True)
class Decision:
    action: str
    reply: outbound.OutboundMessage | None = None


def connect_message() -> outbound.OutboundMessage:
    links = outbound.pairing_links()
    text = (
        "🔗 接入 Karma\n"
        "\n"
        "Karma 的身份、额度与资金边界都由后端判定；聊天窗口只是通道。\n"
        "\n"
        "① 你的 agent：让它跑 Karma MCP（本地 stdio 或远程 HTTP），"
        "它会拿到一个配对码。\n"
        "② 你（主人）：在操作台用已认证的会话批准这次配对，并划好额度与权限。\n"
        "③ 批准后 agent 自己领回凭据 —— 聊天里不会出现任何密钥。\n"
        "\n"
        f"操作台 · 批准配对：{links['pairing']}\n"
        f"操作台 · 我的 agent：{links['agents']}\n"
        "\n"
        "提醒：这个聊天窗口不是资金凭证。Karma 不会在聊天里向你索要私钥、"
        "助记词或验证码；任何人这么要，都是骗子。"
    )
    return outbound.OutboundMessage(
        text=text,
        buttons=(("接入 Karma", "/connect"), ("帮助", "/help")),
        url=links["pairing"],
        url_label="打开操作台",
    )


def help_message() -> outbound.OutboundMessage:
    text = (
        "Karma 聊天通道 · 可用命令\n"
        "\n"
        "/connect —— 接入引导（怎么让 agent 连上 Karma）\n"
        "/help —— 这条帮助\n"
        "\n"
        "这一版只有这两条：聊天里不做支付、不做授权、不改额度。\n"
        "资金相关的动作都在操作台完成 —— 那里有你的登录会话和钱包签名。"
    )
    return outbound.OutboundMessage(text=text, buttons=(("接入 Karma", "/connect"),))


def fallback_message() -> outbound.OutboundMessage:
    text = (
        "我还不认识这条指令。\n"
        "\n"
        "发 /connect 看接入引导，或发 /help 看可用命令。\n"
        "资金相关的操作请到操作台 —— 聊天里不做支付与授权。"
    )
    return outbound.OutboundMessage(text=text, buttons=(("接入 Karma", "/connect"), ("帮助", "/help")))


def decide(event: ChatEvent) -> Decision:
    """把一条入站消息映射成一个动作。未知输入一律**不**产生副作用。"""
    key = (event.button_payload or event.text or "").strip().lower()
    if key in CONNECT_TRIGGERS:
        return Decision(ACTION_CONNECT, connect_message())
    if key in HELP_TRIGGERS:
        return Decision(ACTION_HELP, help_message())
    if event.platform == TELEGRAM:
        return Decision(ACTION_DELEGATE)
    return Decision(ACTION_FALLBACK, fallback_message())