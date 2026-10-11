# Karma 跨平台聊天适配器（S6）—— Telegram / WhatsApp

> 对应总指令第六阶段「跨 Agent 和平台兼容性」。本文件记录**已落地什么、红线在哪、
> 哪些还没做**。与 `karma-mcp-architecture.md` §3 的口径一致：**聊天平台不直连 MCP**，
> 走可信适配器调用后端；适配器不存私钥、不把聊天账号当资金凭证。

## 1. 这一层是什么 / 不是什么

| 是 | 不是 |
|---|---|
| 聊天平台 ↔ Karma 的**通道**（入站归一化 + 出站渲染） | 不是第三套接入方式：agent 走 MCP，人走操作台 |
| 接入**引导**（告诉用户怎么让 agent 连上） | 不是认证：验签只证明「报文来自这个平台」，不证明「这个人是谁」 |
| 通知**下发**（把后端事件推给某个会话） | 不是钱包、不是 agent：不持有任何 Karma 私钥 / Runtime Key |
| 平台差异的收敛层（新增平台只补一个平台模块） | 不含任何动钱 / 授权 / 改额度的路径 |

## 2. 红线（三条，都有用例守着）

1. **先验签，再解析**。Telegram 缺 `TELEGRAM_WEBHOOK_SECRET` → 403；WhatsApp 缺
   `WHATSAPP_APP_SECRET` → 503、签名对不上 → 403；`/notify` 缺配 → 503、token 不对 → 401。
   凭据没配就是没配，不「先放过来」。**顺序也要紧**：解析放在验签前面并不会放行任何
   东西，但会让未认证的调用方从 422 的字段名里读出接口形状 —— 所以 Telegram webhook
   不把 body 声明成 pydantic 参数，`/notify` 的 token 做成 `Depends`，都在解析之前跑。
2. **聊天账号不是资金凭证**。适配器没有任何一条路径能产生 / 扩大 / 动用资金权限；
   入站消息一律经 `commands.decide`，只可能落到白名单动作上。用例
   `test_command_surface_has_no_money_entry` 拿「转账 / 下单 / 改额度」等说法逐个探过。
3. **出站不泄漏**。所有要发进聊天窗口的文本都过 `services/chat_adapters/guard.py`：
   命中 Runtime Key / PEM 私钥 / 原始 65 字节签名 → **拒发**（抛错），不是脱敏后照发。
   交易哈希与证据哈希（`0x` + 64 hex）是公开的，**不**误拦。

## 3. 代码落点

```text
services/chat_adapters/
  __init__.py     包说明与口径
  config.py       控制台地址 / 通知 bearer；只读平台凭据，绝不读私钥
  events.py       入站归一化：Telegram Update 与 WhatsApp webhook → ChatEvent
  guard.py        出站凭据卫生（assert_no_secret / sanitize_text / mask_chat_id）
  outbound.py     OutboundMessage + 两套渲染 + 统一发送
  commands.py     命令面（平台无关，故意做得很小）
  whatsapp.py     WhatsApp Cloud API 客户端 + X-Hub-Signature-256 验签 + 订阅握手
api/routes/chat_adapters.py    FastAPI 路由（挂载于 /v1/adapters）
tests/unit/test_chat_adapters.py   23 例（功能 + 安全）
```

`services/telegram/bot.py` 新增了一个公开包装 `deliver_reply()` —— 适配器要走
「dev 环境默认不发真实消息」那条既有闸门，与其复制判断，不如把它提升成公开契约。
行为与原有私有 `_deliver_reply` 完全一致。

## 4. 出站接口

挂载点 `/v1/adapters`：

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| `GET` | `/status` | 无 | 通道健康视图，**只回布尔与清单**，绝不回显凭据 |
| `GET` | `/whatsapp/webhook` | `hub.verify_token` | Meta 订阅握手，token 对上才回 `hub.challenge` |
| `POST` | `/whatsapp/webhook` | `X-Hub-Signature-256` | 入站；验签用**原始字节**，先 `await request.body()` |
| `POST` | `/telegram/webhook` | `X-Telegram-Bot-Api-Secret-Token` | 入站；认识的命令本适配器答，其余**原样交回**既有 concierge |
| `POST` | `/notify` | `X-Karma-Adapter-Token` | 服务侧推送：把一条通知发到某个会话 |

`/notify` 是后端 / 运维把「钥匙已激活 / 订单已结算 / 争议已开」推到聊天窗口的入口。
**注意**：目前只提供了入口，**后端业务事件还没有自动接进来**（见 §7）。

## 5. 命令面

归一化后的触发词：

| 触发 | 动作 | 效果 |
|---|---|---|
| `/connect`、`/karma`、`/pair`、`接入`、`接入karma` … | `connect` | 回接入三步 + 操作台链接（批准配对 / 我的 agent） |
| `/help`、`/帮助` | `help` | 回可用命令 |
| 其它（Telegram） | `delegate` | 交给既有 concierge（`/start`、`/orders`、自然语言推荐…一条不少） |
| 其它（WhatsApp） | `fallback` | 回一段默认提示（WhatsApp 侧没有 concierge） |

**故意不做**：聊天里支付、授权、改额度、查询他人数据。新增命令前先问一句 ——
这个动作能不能只靠聊天账号就发生？能，就不要加。

## 6. 配置

| 变量 | 必填 | 说明 |
|---|---|---|
| `TELEGRAM_WEBHOOK_SECRET` | Telegram 必填 | 复用既有变量；未配时 prod 一律 403 |
| `WHATSAPP_APP_SECRET` | WhatsApp 必填 | 验 `X-Hub-Signature-256`；没配 = 503 |
| `WHATSAPP_VERIFY_TOKEN` | WhatsApp 必填 | 订阅握手 token；没配 = 503 |
| `WHATSAPP_ACCESS_TOKEN` | 发送必填 | Cloud API 长期 token |
| `WHATSAPP_PHONE_NUMBER_ID` | 发送必填 | Cloud API 发信号码 ID |
| `WHATSAPP_API_BASE` | 否 | 默认 `https://graph.facebook.com/v21.0` |
| `WHATSAPP_SEND_IN_DEV` | 否 | dev/test/local 默认**不发**真实消息，要发得显式打开 |
| `KARMA_ADAPTER_NOTIFY_TOKEN` | `/notify` 必填 | 静态 bearer；没配 = 503 |
| `KARMA_CONSOLE_BASE_URL` | 否 | 默认 `https://karma-network.ai` |
| `KARMA_CONSOLE_PAIRING_URL` | 否 | 直接指定批准配对那一页 |

## 7. 还没做 / 还没验证（如实记）

- **后端事件未自动接入 `/notify`**：入口有了，把 `key_bound` / 结算 / 争议等事件
  自动推过去还需要在业务侧加一处调用（那是改业务代码，单独立项）。
- **微信未做**：本轮范围只有 Telegram / WhatsApp（用户明确收窄）。
  新增平台只需再补一个平台模块 + 一个 webhook 路由，命令面不用动。
- **WhatsApp 真机未跑**：用例全部在 ASGI 测试客户端上跑；真实 Cloud API 凭据、
  真实 phone number、Meta 侧订阅都还没配，所以「消息真的发得出、收得到」**未验证**。
- **Telegram 侧未切换 webhook**：线上仍指向 `/v1/telegram/bot/webhook`。
  切到 `/v1/adapters/telegram/webhook` 才会多出 `/connect` 引导（其余功能不变）。
- **没有持久化绑定**：本版适配器不知道「这个会话是谁的」。所以它不发个性化通知 ——
  `/notify` 的 `chat_id` 由调用方给出。会话 ↔ 身份绑定需要操作台签发的一次性链接，
  那是一个独立的安全动作（涉及一次性 token 存储），未在本轮做。
- **操作台未加「绑定聊天渠道」按钮**：同上，属于绑定链路的后续。

## 8. 安全用例清单

`tests/unit/test_chat_adapters.py`（23 例，全绿）中与安全直接相关的：

| 用例 | 考什么 |
|---|---|
| `test_telegram_webhook_rejects_missing_or_wrong_secret` | 无 / 错 secret header → 403 |
| `test_telegram_webhook_fails_closed_when_secret_is_unset_in_prod` | prod 未配 → 403，不是放行 |
| `test_whatsapp_webhook_rejects_bad_or_absent_signature` | 无签名 / 错签名 / 改包重放 → 403 |
| `test_whatsapp_webhook_fails_closed_without_app_secret` | App Secret 没配 → 503 |
| `test_whatsapp_handshake_fails_closed_without_verify_token` | 握手 token 没配 → 503 |
| `test_notify_requires_a_configured_token_then_a_matching_bearer` | 503 / 401 / 200 三段式 |
| `test_notify_refuses_credential_shaped_text` | 通知里的疑似凭据 → 400 |
| `test_status_endpoint_never_echoes_secrets` | 状态接口不回显任何凭据 |
| `test_command_surface_has_no_money_entry` | 命令面无动钱入口 |
| `test_adapter_package_never_reaches_into_money_or_keys` | 源码级：不 import 链 / 钱包 / 记账 |
| `test_guard_blocks_credentials_but_keeps_public_hashes` | 拦凭据、不误拦公开哈希 |
| `test_telegram_webhook_verifies_signature_before_parsing_body` | 坏报文 + 未验签 → 403（不是 422） |
| `test_notify_authenticates_before_body_validation` | 未认证 → 503/401（不是 422） |
| `test_outbound_refuses_to_send_a_credential` | 出站拒发 |