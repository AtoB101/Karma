# Karma 通用 Agent MCP Server —— 工具目录与接口契约（第二阶段 · P2）

> 上游：`docs/mcp/karma-mcp-audit.md`、`docs/mcp/karma-mcp-architecture.md`。
> 本文件定义**工具语义与契约**。名称可在实现时按现有命名规范微调，语义不得改变。

---

## 1. 权限等级与开放顺序

| Tier | 含义 | 是否动钱 | 何时开放 |
|---|---|---|---|
| T0 | 只读状态（连接 / 身份 / 授权 / 交易 / 信誉查询） | 否 | 第二阶段 S2/S3 |
| T1 | 授权变更（创建 / 更新 / 撤销授权） | 否（但决定钱的上限） | 第二阶段 S3 |
| T2 | 交易与交付（下单 / 确认 / 证据） | 是（受额度约束） | 第三阶段起，逐项 |
| T3 | 结算与争议（结算 / 退款 / 争议） | 是（资金划转） | 最后开放，且需单独批准 |

**默认关闭写操作**：未在配置中显式开启的 T2/T3 工具不注册（fail-closed）。

---

## 2. 目标工具 → MCP 工具 → 后端落点 映射

| 目标工具（指令） | MCP 工具名 | 后端落点 | 权限 | Tier |
|---|---|---|---|---|
| `karma_connect` | `karma_connect` | `POST /v1/agents/connect-challenge` → 配对码流程 | — | T0 |
| `karma_get_connection_status` | `karma_get_connection_status` | `POST /runtime/permissions`、`GET /runtime/permissions` | — | T0 |
| `karma_get_identity_status` | `karma_get_identity_status` | `GET /v1/identity/{id}/verification`、`/activation` | — | T0 |
| `karma_start_identity_verification` | `karma_start_identity_verification` | `POST /v1/identity/{id}/verification/provider/session` | — | T0 |
| `karma_request_authorization` | `karma_request_authorization` | 返回**钱包待签**消息（`build_create_key_message` 同构）→ 主人签 → `POST /runtime/create-key` | — | T1 |
| `karma_get_authorization_status` | `karma_get_authorization_status` | `GET /runtime/policy`、`/permissions` | — | T0 |
| `karma_get_policy` | `karma_get_policy` | `GET /runtime/policy` | — | T0 |
| `karma_update_authorization` | `karma_update_authorization` | 铸新 key（钱包签名）+ `POST /runtime/revoke-key` 旧 key | — | T1 |
| `karma_revoke_authorization` | `karma_revoke_authorization` | `POST /runtime/revoke-key`、`POST /v1/agents/owner-revoke` | — | T1 |
| `karma_create_intent` | `karma_create_intent` | `POST /v1/payment-intents`、`POST /v1/discovery/intent` | — | T2 |
| `karma_create_transaction` | `karma_create_transaction` | `POST /runtime/place-order`、`POST /v1/trade/orders/launch` | `place_order` | T2 |
| `karma_get_transaction_status` | `karma_get_transaction_status` | `GET /runtime/task-status/{task_id}`、`GET /v1/trade/orders/{id}` | — | T0 |
| `karma_confirm_transaction` | `karma_confirm_transaction` | `POST /v1/payment-codes/{id}/accept`、`POST /v1/confirmations/sessions/{id}/decide` | — | T2 |
| `karma_submit_evidence` | `karma_submit_evidence` | `POST /runtime/submit-bundle`、`POST /v1/evidence/bundles` | `submit_receipt` | T2 |
| `karma_verify_evidence` | `karma_verify_evidence` | `POST /v1/evidence/{id}/verify`、`/v1/delivery-verification/{id}/verify` | `verify_voucher` | T2 |
| `karma_get_receipt` | `karma_get_receipt` | `POST /runtime/submit-receipt`、`GET /v1/receipts/*` | `submit_receipt` | T2 |
| `karma_get_settlement_status` | `karma_get_settlement_status` | `GET /v1/settlement/{task_id}`、`/transitions` | — | T0 |
| `karma_request_refund` | `karma_request_refund` | `POST /v1/settlement/{task_id}/dispute`、`/v1/escrow/*` | `request_settlement` | T3 |
| `karma_open_dispute` | `karma_open_dispute` | `POST /v1/settlement/{task_id}/dispute`、`POST /v1/arbitration/cases` | — | T3 |
| `karma_get_reputation` | `karma_get_reputation` | `GET /v1/reputation/{agent_id}`、`/rewards` | — | T0 |
| `karma_get_risk_result` | `karma_get_risk_result` | `POST /v1/risk/assess`、`GET /v1/responsibility/model/public-risk`（**仅公开投影**） | — | T0 |

**不得**为 `karma_get_risk_result` 暴露任何内部风控接口（私有域，审计 §5）。

---

## 3. 工具契约明细

### 3.1 T0 —— 连接与身份（第二阶段 S3，**已实现**）

#### `karma_connect`

- **用途**：发起配对，把用户的 Karma 身份与当前 Agent 绑定。**不授予资金权限。**
- **前置**：无（未配对时唯一可调工具）。
- **入参**：`agent_name: str`（必填）、`identity_hint: str | None`。
- **流程**：返回 `user_code` + `verification_uri`（主人在 Console 输码/扫码批准）。
- **返回**：`{status, user_code, verification_uri, expires_at, public_key_attached, agent_fingerprint, next_step}`。`agent_fingerprint` = agent 公钥的 sha256 前 16 位，与操作台待批准卡片上显示的那串同构（`services/runtime_key_service.agent_binding_fingerprint`，全系统唯一口径），供主人核对「操作台这条申请就是聊天里这个 agent」。
- **失败语义**：错误一律不改状态；`user_code` 过期需重新发起。
- **安全**：不得仅凭聊天平台用户名认定身份（架构 §6）。

#### `karma_get_connection_status`

- **用途**：查询当前凭据的连接/激活状态。
- **入参**：无。
- **后端**：`GET /runtime/permissions`（读路径，不落调用记录）。
- **返回**：`{connection, key_binding, agent_bound, permissions, limits, expires_at}`；`connection ∈ {unconfigured, pending_activation, active, revoked}`。
- **失败语义**：无 key → `unconfigured`（不是错误）。

#### `karma_get_identity_status`

- **入参**：`identity_id: str | None`（缺省 = 当前 key 绑定身份）。
- **后端**：`GET /v1/identity/{id}/verification`、`/activation`。
- **返回**：`{identity_id, kyc_status, face_activated, bound_wallet_masked, verification_level}`；钱包地址**脱敏**。
- **失败语义**：未认证 → `kyc_status=none`，不是错误。

#### `karma_start_identity_verification`

- **入参**：`identity_id: str`、`method: Literal["face","kyc"] = "face"`。
- **后端**：`POST /v1/identity/{id}/verification/provider/session`（返回会话/链接）。
- **返回**：`{session_id, action_url, expires_in_seconds}`。
- **失败语义**：已有有效会话可复用；不得重复开单。
- **边界**：**刷脸不可被钱包签名替代**（审计 §7.1-B）。

#### `karma_get_authorization_status` / `karma_get_policy`

- **入参**：无。
- **后端**：`GET /runtime/policy`、`GET /runtime/permissions`、`GET /runtime/capacity`。
- **返回**：`{permissions, single_limit, daily_limit, daily_used, remaining_today, expires_at, allowed_task_types}`。
- **失败语义**：无 key → `unconfigured`。

#### `karma_get_transaction_status`

- **入参**：`task_id | order_id`（至少一个）。
- **后端**：`GET /runtime/task-status/{task_id}`、`GET /v1/trade/orders/{order_id}`。
- **返回**：统一视图 `{task_id, order_id, status, state_machine, voucher_id, settlement_status, updated_at}`。

#### `karma_get_settlement_status`

- **入参**：`task_id: str`。
- **后端**：`GET /v1/settlement/{task_id}`、`/transitions`。
- **返回**：`{task_id, settlement_state, transitions[], settled_amount, currency}`。

#### `karma_get_reputation`

- **入参**：`agent_id: str`。
- **后端**：`GET /v1/reputation/{agent_id}`、`/rewards`。
- **返回**：公开信誉画像；**不得**包含任何内部评分算法细节。

#### `karma_get_risk_result`

- **入参**：`identity_id: str`。
- **后端**：`POST /v1/risk/assess` 或 `GET /v1/responsibility/model/public-risk`。
- **返回**：**仅公开投影**（如风险等级 / 公开标记）；**永不**返回内部特征、权重、模型参数。

### 3.2 T1 —— 授权（第二阶段 S3，**已实现**）

#### `karma_request_authorization`

- **用途**：把用户自然语言权限意图 → **结构化策略预览** → 用户确认 → 钱包签名 → 铸造 Runtime Key。
- **绝对禁止**：不得由 Agent 或模型自行签发资金权限；不得跳过用户确认；不得代替用户签名。
- **入参**：`agent_name`、`permissions: [str]`、`single_limit: float`、`daily_limit: float`、`expire_time: str | None`、`agent_binding: str`（**必填** —— 后端 `runtime_require_agent_binding` 拒绝不记名钥匙，MCP 提前拦）、`wallet_address: str`（**可留空** —— 留空时 MCP 用主人身份上已绑定的钱包自动补上，用户不必把地址贴进聊天）。
- **指纹锚**：待签文本里的 `agent_public_key_fingerprint` 由 MCP 用**本机 agent 公钥**自动填（`KARMA_AGENT_PRIVATE_KEY` → 公钥 → sha256 前 16 位，与 `services/runtime_key_service.agent_binding_fingerprint` 同口径）。主人签下的就是「这把钱钥匙铸给哪把 agent 公钥」；绑定那一刻服务端重算指纹，对不上（换公钥 / 偷 key 的人抢先绑）一律 403，必须吊销重铸。本机没有 agent 私钥时该行留空 —— 回到「签名不约束绑定公钥」的老行为，绝不因此多放行权限。
- **返回（第一步）**：`{preview: {...}, sign_message: "<与后端 build_create_key_message 同构的待签文本>", next_step}`。
- **返回（第二步，用户签完回传签名）**：调 `POST /runtime/create-key` → `{key_id, key_fingerprint, permissions, limits, expires_at}`（**只回指纹，绝不回 key 明文之外的任何秘密**；key 明文只在凭据文件里）。
- **失败语义**：用户未确认 → 不产生任何后端变更；签名不匹配 → 后端 403，MCP 原样透传为 `forbidden`。

#### `karma_update_authorization`

- **语义**：改额度/边界 = **铸新 key（重新钱包签名）+ 注销旧 key**。不存在「原地改」。
- **入参**：同 `karma_request_authorization`，外加 `revoke_key_id`。
- **顺序**：先铸新、再撤旧；任一步失败都不得留下「两把都能花」的状态（撤销失败必须显式报错并提示用户）。

#### `karma_revoke_authorization`

- **用途**：**立即**停用某把 key（对应操作台「一键停用」）。
- **入参**：`key_id: str | None`（缺省 = 当前 key）、`agent_id: str | None`。
- **后端**：`POST /runtime/revoke-key`、`POST /v1/agents/owner-revoke`。
- **返回**：`{revoked: true, key_id, revoked_at}`。
- **安全**：撤销后旧权限**立即**不可再用（审计 §9 验收项）。

### 3.3 T2/T3 —— 交易 / 交付 / 结算（工具已注册，默认关闭）

每个 T2/T3 工具**必须**满足：

1. 调用前 L3 快速拒绝（无 key / 权限不含该动作）；
2. 请求带 `client_nonce`（≥8 字符），后端落库幂等回放；
3. 交易创建另带 `Idempotency-Key`；
4. 后端权威判定（身份 / 绑定 / 有效期 / 范围 / 单笔 / 日额度 / 对象 / 是否需二次确认 / 风控 / 状态机）；
5. **金额与文档口径必须一致**：`amount` 为 USDC 计价；精度按任务 `task_precision`；
6. 返回**永不**把「调用成功」表述为「交易成功」；以 `status` + `state_machine` 为准。

`karma_create_transaction` 入参（对齐 `RuntimePlaceOrderBody`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `requirement_text` | str（1..32000） | 是 | 需求原文（Intent） |
| `amount` | float > 0 | 是 | USDC 金额 |
| `seller_identity_id` | str | 否 | 指定卖方；缺省走发现 |
| `client_nonce` | str（8..128） | 是 | 幂等/防重放 |
| `negotiate_a2a` | bool = true | 否 | 是否 A2A 协商 |
| `auto_complete` | bool = false | 否 | 是否自动完成 |
| `confirmation_session_id` | str | 否 | 人工确认会话 |
| `important_fields_capture_id` | str | 否 | 已双签的 Important Fields |

返回（对齐后端）：`{order_id, task_id, status, voucher_id, payment_code?, readiness?, trace_id?, awaiting_owner_confirmation}`。

`awaiting_owner_confirmation` = **未成交**：超自动额度时不建单不扣钱，等主人在操作台确认。MCP 必须如实转达，**不得**提示「已下单成功」。

---

## 4. 工具命名与开放注册

- 命名：`karma_<verb>_<object>`，全小写下划线。
- 注册：仅注册当前 Tier 允许的工具；T2/T3 默认关闭，需显式配置开启。
- 每个工具必须有：`description`（含前置条件与失败语义）、严格输入 Schema、明确返回结构。

**实际注册数**（`server.py` 按 Tier 白名单 fail-closed）：

| 配置 | 注册工具数 |
|---|---|
| 默认（T0+T1） | 17 |
| `+KARMA_MCP_ENABLE_TIER2=1` | 25 |
| `+KARMA_MCP_ENABLE_TIER3=1` | 28 |

## 5. 待确认项 —— 现状

1. 配对码接口：**已定** —— 直接复用 `/v1/agent-pairing/request|claim`（与 `karma-openclaw` 同一通道）。
2. 授权更新：**已定** —— 后端无「原地改」入口，走**铸新 + 撤旧**（强行改会破坏后端验签预期）。
3. 聊天侧签名下发：**未定** —— Console 已有深链；聊天侧（签名链接 / 二维码）待 S6 与平台适配一并定。
