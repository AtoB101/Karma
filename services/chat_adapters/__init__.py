"""跨平台聊天适配器（S6）—— Telegram / WhatsApp。

设计口径见 ``docs/mcp/karma-mcp-platform-adapters.md``：

- 适配器是**通道**，不是 agent、也不是钱包：不持有任何 Karma 私钥、助记词或
  Runtime Key，也不代用户签名。
- 聊天账号**不是**资金凭证：本通道只做「接入引导 + 通知下发」，没有任何一条
  命令能产生、扩大或动用资金权限。
- 平台凭据没配就是没配（fail-closed）：webhook 一律 403 / 503，绝不静默放行。

平台差异只收敛在 ``events``（入站归一化）/ ``outbound``（出站渲染）/ ``whatsapp``
（平台客户端）三处；命令面 ``commands`` 与平台无关，新增平台（如微信）只需再补
一个平台模块，不必改命令面。
"""
from services.chat_adapters import commands, config, events, guard, outbound, whatsapp

__all__ = ["commands", "config", "events", "guard", "outbound", "whatsapp"]