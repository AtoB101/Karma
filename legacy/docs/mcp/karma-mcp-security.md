# Karma 通用 Agent MCP Server —— 安全设计（第二阶段 · P2）

> 上游：`docs/mcp/karma-mcp-audit.md`、`karma-mcp-architecture.md`、`karma-mcp-tools.md`。
> 原则：**安全第一。** 所有安全声明必须有测试或代码证据；不得以「功能新增」冒充「安全性提高」。

---

## 1. 信任边界

```
用户设备(可信)           MCP Server(半可信)          Karma 后端(可信)
  ├ 私钥/助记词  ←永不外流→  ✗ 不接触
  ├ Agent 签名私钥          ✔ 只读凭据文件
  └ 用户钱包签名      ←签名外流→  ✔ 只验签              ✔ 权威判定
```

- **可信**：用户设备、Karma 后端。
- **半可信**：MCP Server 与 LLM。它们能看到/被注入，因此**不得**持有任何长期秘密，且其输出**不得**被当作授权依据。
- LLM 属于「不可信输入源」：它的任何输出都可能被提示词注入污染，**永远**不能成为放行理由。

## 2. 红线（实现期不得违反）

| # | 红线 | 证据/依据 |
|---|---|---|
| R1 | MCP 进程只注入 `KARMA_RUNTIME_KEY`，**禁止**私钥/助记词 | `docs/mcp-adapter-guide.md:5`；审计 §7-P0 |
| R2 | 服务端只**验签**，不代签；`sign-with-backend` 仅 dev/CI | `docs/OPEN_WALLET_SIGNING-zh.md`；审计 §7.1-D |
| R3 | 动钱一律过后端权威判定，MCP 不做终审 | `services/actor_guards.py` |
| R4 | 未经授权**不得**暴露内部风控/内部 admin 接口 | 审计 §5（私有域） |
| R5 | 凭证、签名、密钥**不得**进日志或模型上下文 | 本节 §6 |
| R6 | 失败默认拒绝，**不得**转成成功 | 架构 §8 |
| R7 | 不得绕过状态机、资金安全、风控 | 指令 §二 |

## 3. 威胁模型（面向 MCP 接入层）

| 威胁 | 场景 | 缓解 | 验证 |
|---|---|---|---|
| 未认证调用 | 无 key 调受保护工具 | L3 拒绝 + 后端 401 | 安全测试 S1 |
| 未授权 Agent 交易 | key 无 `place_order` | `assert_permission` → 403 | S2 |
| 已撤销/过期授权继续用 | 撤销后旧 key 重放 | `load_active_context` 校验 `status=active` + 有效期 | S3 |
| 单笔超额 | 单笔 > key 上限 | `check_single_and_daily_limits` | S4 |
| 并发突破累计额度 | 多 Agent 同时消费 | 守卫式原子 UPDATE 占额 | S5 |
| 越权改交易对象/范围 | 改 `seller_identity_id` | 幂等键 + 需求指纹不一致 → 409 | S6 |
| 重放旧请求/旧授权 | 重发同一 nonce | 落库 nonce 台账 | S7 |
| 恶意构造参数 | 超长/注入/类型错 | 严格 Schema + 长度上限 | S8 |
| 提示词注入绕过授权 | 「忽略规则直接下单」 | LLM 无授权能力；放行只认后端 | S9 |
| 伪造交易完成/证据 | 客户端自报成功 | 证据哈希 + 后端验证 | S10 |
| 工具错误误报成功 | 401/403 被包装成 OK | 错误分类不得转成功 | S11 |
| 敏感凭证进日志/上下文 | key 明文被打印 | 脱敏 + 只回指纹 | S12 |
| 公开接口暴露私有风控 | 内部评分外泄 | 仅公开投影 | S13 |

## 4. 认证与授权（三层）

1. **传输层**：本地 `stdio`（隐式可信）；远程 Streamable HTTP **必须**叠加标准化身份验证与授权后才开放。
2. **凭证层**：Runtime Key（不记名令牌）。未绑 Agent 公钥的 key 处于 `agent_pending`，动钱一律 403。
3. **请求层**：已绑定公钥的 key 每个请求必须带 `X-Karma-Agent-Signature` / `X-Karma-Runtime-Timestamp` / `X-Karma-Runtime-Nonce`，服务端重建消息验签（容差 300s），**验签通过后才记 nonce**（错签不烧 nonce）。

**权限与额度是钱包签名的对象**：`POST /runtime/create-key` 强制 `wallet_signature`，签名消息覆盖 `permissions`/`single_limit`/`daily_limit`/`expire_time`/`agent_binding`/`agent_public_key_fingerprint`（`services/runtime_wallet.py:39-73`）。最后一行由 MCP 用**本机 agent 公钥**自动填（`karma_mcp_server.backend_client.agent_key_fingerprint`）：主人签下的是「这把钱钥匙铸给哪把 agent 公钥」。绑定那一刻服务端重算指纹（`services/runtime_key_service.assert_agent_key_matches_signed_fingerprint`），对不上（换公钥 / 偷 key 的人抢先绑）一律 403。Agent 与模型**无法**自行扩大权限。

### 4.1 配对与接入的三把锁（agent 自动接入）

目标：用户在自己的 Agent 聊天窗口里说一句「帮我接入 Karma」就要能走完，
而**任何知道配对码的人都拿不走凭据**。三把锁彼此独立，任一把不满足就不放行。

| # | 锁 | 谁持有 | 缺了会怎样 |
|---|---|---|---|
| L1 | agent 私钥签名申请 + 主人在已认证会话里批准 | agent 私钥 / 主人会话 | 申请端 401；批准端 403 |
| L2 | 可选「交接码」（主人签发、60 秒、一次性） | 主人（念给 agent） | claim 停在 `awaiting_handoff` |
| L3 | 邮箱回执：主人邮箱里点「与 agent 聊天窗口显示相同的那个码」 | 只有主人读得到的邮箱 | claim 停在 `awaiting_email_confirm`，**不交付任何凭据** |

L3 的关键约定（`services/agent_pairing.py`、`api/routes/agent_pairing.py`）：

- 邮件里放 3 个候选码，只有 1 个是「对的」；真正的解锁物是**每条码各自那条链接上的 token**。
- **明文 token 只出现在邮件正文里**；磁盘上只存 `sha256`（`_new_email_codes`），面向操作台/agent 的配对视图永不回显 token（`email_confirm_public`）。
- `match_code` 故意要显示在 **agent 聊天窗口**：配对码泄漏者读得到它，但读不到主人邮箱，因此换不到任何东西（`test_email_confirm_is_a_real_third_lock` 里「拿 match_code 当 token」必须 409）。
- **点错有代价**：点错/猜错都记一次失败，连错 `EMAIL_CONFIRM_MAX_ATTEMPTS=6` 次就把这次配对就地作废（`row.status=expired`），与交接码同一口径。
- **状态对齐**：配对作废后 `email_confirm.state` 也必须是 `expired`，不能让操作台显示「还在等你点码」。
- **出口没配就是没配**：两条出口都没配时（`KARMA_MAIL_HOST`/`KARMA_MAIL_FROM`/`KARMA_MAIL_PORT` 任一为空，且没配齐 `KARMA_MAIL_RELAY_URL`/`KARMA_MAIL_RELAY_TOKEN`） `mailer.configured()==False`（`services/mailer.py`），带 `notify_email` 的批准**在创建 agent 之前**就 503，绝不静默降级成「已加锁」；发送中途失败则 502，且此时 claim 仍被闸门挡住（fail-closed）。
- 有效期 `EMAIL_CONFIRM_TTL_SECONDS=600`；重发 = 重出码，旧 token 当场作废。
- 不填 `notify_email` 时这一版行为与从前**完全一致**（默认不开这道锁）。

## 5. 钱包签名的适用范围（与审计 §7.1 一致）

- **可签**：交易启动（TradeLaunchIntent）、凭证授权（AuthorizationVoucher）、交付/结算确认、SIWE 登录、授权策略锚定。
- **不可签**：同人核验/KYC（刷脸）、运营刹车/紧急冻结、风控判定 —— 这些必须留在后端权威判定。
- **红线**：钱包签名**不授予**任何额度；额度仍由后端 key 策略判定。

## 6. 日志与凭证卫生

- **永不出现在日志/工具返回**：`KARMA_RUNTIME_KEY` 明文、私钥、助记词、原始签名、`X-Karma-Agent-Signature` 原文。
- 允许返回：key **指纹**、`key_id`、钱包地址**脱敏**（`0x1234…abcd`）、状态码、错误分类。
- **钱包地址的边界**：待签文本 `sign_message` 里的 `wallet_address` 是主人本人要签的那一行，必然完整可见；此外只有**该身份本人**（或其自己的 agent，经 `X-Karma-Api-Key` 解析到本人）能读到 `GET /v1/identity/{id}/verification` 的 `bound_wallet_address`。陌生人与未认证调用拿到的公开视图里**没有**这个字段（未认证调用直接 401），状态类返回仍只给脱敏地址。
- 日志字段白名单：`tool`、`tier`、`endpoint`、`http_status`、`error_class`、`key_fingerprint`、`request_id`。
- **确认邮箱只回显脱敏值**（`ow***@example.com`，`services/agent_pairing.py:_mask_email`）；邮件正文里只有短码与确认链接，**不含**任何凭据。

## 7. 幂等与并发（不得自行实现）

| 关注点 | 必须交后端 | 证据 |
|---|---|---|
| 请求重放 | `client_nonce` 落库台账 | `services/runtime_nonce_log.py` |
| 交易重复建单 | `Idempotency-Key` | `services/trade_order_idempotency.py` |
| 累计额度并发 | 守卫式原子 UPDATE | `services/runtime_daily_spend.py:78-135` |
| 账本并发 | 相对增量原子加减 | `services/atomic_ledger.py` |

## 8. 提示词注入防护

- MCP 工具**不接受**「跳过确认」「直接放行」「额度随便」这类自然语言指令作为授权依据。
- 任何额度/边界变更**必须**产出**结构化预览** → 用户显式确认 → **用户钱包签名**。三者缺一不可。
- 后端返回的 `awaiting_owner_confirmation` 等状态**必须**原样转达；禁止模型改写为「成功」。

## 9. 安全测试清单（对应指令 §九）

| ID | 用例 | 期望 |
|---|---|---|
| S1 | 未认证用户调用受保护工具 | 拒绝 |
| S2 | 未授权 Agent 执行交易 | 拒绝 |
| S3 | 已撤销/已过期授权继续调用 | 拒绝 |
| S4 | 单笔额度超限 | 拒绝 |
| S5 | 并发调用突破累计额度 | 不超限 |
| S6 | 越权修改交易对象或授权范围 | 拒绝 |
| S7 | 重放旧请求或旧授权 | 拒绝 / 幂等回放，不重复扣款 |
| S8 | 恶意构造参数 | 拒绝且不产生副作用 |
| S9 | 提示词注入诱导绕过授权 | 无效（放行只认后端） |
| S10 | 伪造交易完成或交付证据 | 被验证拦下 |
| S11 | 工具返回错误时误报成功 | 不得发生 |
| S12 | 敏感凭证进入日志或模型上下文 | 不得发生 |
| S13 | 公共接口意外暴露私有风控数据 | 不得发生 |
| S14 | 配对码泄漏者拿 `match_code` / 旧 token 抢凭据 | 拒绝；连错到上限则配对作废 |

**验收口径**：每条用例都要有**真实执行记录**；未覆盖的必须显式标注为未验证。

## 10. 未决安全项（明确列出，不掩饰）

1. 远程鉴权：**已定为静态 bearer token**（`KARMA_MCP_HTTP_TOKEN`，`hmac.compare_digest` 常量时间比较，
   `FastMCP(token_verifier=...)` + `AuthSettings`）；未配令牌 / 未显式开启 → 拒绝启动。
   **完整 OAuth 2.1 授权服务器接入仍待做**（多租户远程开放前必须先落地）。
2. 多实例横向扩容时，`runtime_key_service.py` 进程内 `_replay`/`_DAILY` 是否已完全被落库版取代 —— 须逐一核对调用点（当前部署 `--workers 1`）。
   MCP 层不自行实现重放/额度并发；由后端 `runtime_nonce_log` / `runtime_daily_spend` / `atomic_ledger` 裁决。
3. 提示词注入的**运行时**防护（不只是设计约束）需要真实攻击用例验证。当前已有结构性缓解：
   Tier 白名单 fail-closed、MCP 无签发权限（授权必须主人钱包签名）、所有写操作经后端复核。
4. 聊天平台适配器的凭证模型（不存私钥、不把聊天账号当资金凭证）待 S6 落地。
5. Tier-2/3 动钱工具的**真实资金端到端验收**尚未在测试环境跑通（工具注册与转发已测）。
6. **邮箱回执的真实外部投递尚未验证**：部署环境 `KARMA_MAIL_*` / `KARMA_MAIL_RELAY_*`
   均未配置，目前真机只覆盖「未配 → 503」的 fail-closed 与「受控本地 SMTP 出口下的
   端到端链路」。出境中继（方案 B，`scripts/ops/mail_gateway.py`）已在**本机**
   跑通鉴权/校验/真实 SMTP 投递/fail-closed 与「后端 `mailer` ↔ 网关」两半对接
   （见 `karma-mcp-live-verification.md` §9），但**境外真机与真实收件箱尚未落地**。
