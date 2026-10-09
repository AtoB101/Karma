# Karma 通用 Agent MCP Server —— 第一阶段审计报告

- 审计对象：本机检出的 Karma 主仓（`work/sync`），分支 `main`，HEAD `33422e4`
- 审计日期：2026-10-10
- 审计性质：**只读**。本阶段未修改任何生产代码、未提交、未部署、未执行真实资金交易。本文件是唯一新增物（未跟踪）。
- 对应指令：《Karma 通用 Agent MCP Server — 工程开发总指令》第三节「第一阶段：完整代码审计」

---

## 0. 结论先行（可行性判断）

**方案在 Karma 现有基础上可行。** 绝大多数工作是把**已经存在并被测试覆盖**的后端能力接到 MCP 薄适配层，不是新建身份系统、支付系统或结算系统。

- 身份 / 授权：`services/runtime_key_service.py`（`KRM_RT_` Runtime Key + Agent Ed25519 签名钉死 + 权限集 + nonce 防重放 + 日额度）已完整落地并有测试。
- 交易：`services/trade_order_pipeline.py` + `services/trade_order_idempotency.py`（`Idempotency-Key` 幂等回放）已落地。
- 资金约束 / 状态机：`karma-core/contracts/core/KarmaBilateral.sol` 的 `BillState` / `BindingState` 状态机 + 链上不变量；后端 `services/atomic_ledger.py`（守卫式原子 UPDATE）已落地。
- 证据 / 结算 / 信誉 / 争议 / 人工确认：`/v1/evidence`、`/v1/execution-receipt`、`/v1/settlement`、`/v1/reputation`、`/v1/arbitration`、`/v1/confirmations` 路由与服务全部存在。

**必须先处理的三个障碍（阻塞项）：**

1. **已有 `packages/karma-mcp` 把钱包私钥放进 MCP 进程**（`karma_mcp/chain.py:130` 读 `KARMA_PRIVATE_KEY` 直接签链上交易）。这与总指令红线「不得将私钥交给 LLM / MCP 适配层不得直接操作生产私钥」**直接冲突**。`packages/karma-openclaw` 是正确样板（只注入 Runtime Key，不注入私钥）。新 MCP 必须走 Runtime Key / 网关代签模型。
2. **私有仓（风控引擎）在本机不存在，无法验证。** 公开侧只有 `/v1/risk/assess`、`/v1/responsibility/model/public-risk`、`/v1/standards/accept-fulfillment/sellers/{seller_id}/risk` 等**公开投影**。`karma_get_risk_result` 一类工具只能做「公开侧可验证的部分」，内部风控算法不得暴露、也无法在此环境验证。
3. **口径纠正**：总指令第七节提到的 `NonCustodialAgentPayment` / `SettlementEngine` 在当前仓库已是**废弃路径**（`README.md` 明确活跃路径是 `KarmaBilateral`）。MCP 的复用对象应写 **KarmaBilateral + Runtime Gateway**，而不是旧类。

---

## 1. 当前已实现的功能及代码位置

### 1.1 仓库与服务边界

| 层 | 位置 | 证据 |
|---|---|---|
| FastAPI 应用入口 | `api/app.py` | 约 50 个 router include；390 条 HTTP 路由 |
| API 路由 | `api/routes/*.py` | 49 个路由文件（`agents.py` / `runtime_gateway.py` / `trade.py` / `settlement.py` / `evidence.py` / `arbitration.py` / `verifiers.py` / `confirmations.py` / `reputation.py` / `identities.py` / `identity_kyc.py` / `vouchers.py` / `x402.py` 等） |
| 业务服务 | `services/*.py` | 约 110 个模块 |
| 数据模型 / 迁移 | `db/models/orm.py`、`db/migrations/versions/` | Alembic；`RuntimeKeyDailySpendModel`（0021）、`RuntimeSafetyModeModel`（0060）等 |
| 合约 | `karma-core/contracts/core/` | `KarmaBilateral.sol` / `KarmaIdentityRegistry.sol` / `KarmaReputationAnchor.sol` / `VerifierRegistry.sol` 等 13 个 |
| SDK | `packages/karma-sdk`（Py+TS）、`packages/sdk`（TS HTTP）、`packages/karma-runtime-sdk`、根 `sdk/`（`client.py` / `runtime_client.py` / `openclaw_agent.py` / `openmanus_agent.py` / `x402/`） |
| Agent 适配器 | `packages/karma-openclaw`、`packages/karma-openmanus`、`packages/karma-connect`、`packages/karma-a2a-bridge` |

### 1.2 已实现的 MCP 能力（两个包）

**A. `packages/karma-mcp`（已有，薄、但危险面大）**
- 仅 2 个业务模块：`karma_mcp/server.py`、`karma_mcp/chain.py`。`FastMCP("karma-mcp")`，`mcp.run(transport="stdio")`。
- 9 个工具：`karma_lock` / `karma_bind` / `karma_settle` / `karma_unlock` / `karma_get_bill` / `karma_get_binding` / `karma_check_invariant`（直连链上）+ `karma_fulfill_intent` / `karma_discover_for_intent`（HTTP 代理 `KARMA_API_BASE`）。
- **无任何测试文件。**
- **风险**：`karma_mcp/chain.py:130` `pk = os.environ["KARMA_PRIVATE_KEY"]` → 进程内持有私钥并签名。见第 7 节。

**B. `packages/karma-openclaw`（已有，成熟 —— 新 MCP 的参考实现）**
- 65 个工具（`p0_tools.py` 19 + `phase1_tools.py` 15 + `server.py` 17 + `bilateral_tools.py` 6 + `phase2_tools.py` 1 + `pairing_tools.py` 4 + `runtime_tools.py` 3）。
- 覆盖：配对连接（`karma_pairing_start/status/claim/local_status`）、Runtime Key 绑定（`karma_runtime_bind_key/binding_status/await_activation`）、授权策略（`karma_save_automation_policy` / `karma_get_automation_policy` / `karma_check_automation_readiness`）、交易（`karma_launch_trade_order` / `karma_get_trade_order` / `karma_create_payment_code` / `karma_accept_payment_code`）、证据（`karma_submit_evidence_bundle` / `karma_get_evidence_bundle` / `karma_submit_execution_receipt` / `karma_build_execution_receipt_step`）、结算（`karma_get_settlement` / `karma_settlement_*` / `karma_runtime_request_settlement`）、双边链上（`karma_bilateral_lock/bind/settle/finalize/status/dispute`）、x402（`karma_x402_fetch`）。
- 安全设计（**应复用**）：Runtime Key 与 agent 公钥钉死、每请求签名；配对方向固定（Agent 出 `user_code` → 主人在 Console 输码批准 → 凭据写 `~/.karma/agent.env` 0600，只回指纹）；`guard.py` 提供 `require_valid_handoff` / `server_attestation_required` / `buyer_confirm_allowed`；高危动作默认**手动**。
- 测试：`packages/karma-openclaw/tests/` 13 个测试文件。

### 1.3 资金安全与状态机（系统最关键部分）

| 主题 | 位置 | 说明 |
|---|---|---|
| 链上状态机 | `karma-core/contracts/core/KarmaBilateral.sol:109-121` | `BillState{MINTED,BOUND,BURNED}`；`BindingState{ACTIVE,PENDING,SETTLED,DISPUTED,REFUNDED}` |
| 链上不变量 | 同上 `:47` | `freeBalance[a] + boundBalance[a] == totalMintedByAddr[a]`；`totalBillSupply == totalLocked`（`karma_check_invariant` 可验） |
| 后端原子记账 | `services/atomic_ledger.py` | 守卫式单条 UPDATE，`rowcount==0` → 409；只做相对增量（`col = col + delta`） |
| 日额度并发安全 | `services/runtime_daily_spend.py:78-135` | `try_reserve_daily_spend` 用带守卫条件的 UPDATE 串行化；`RuntimeKeyDailySpendModel` 落库（迁移 0021） |
| 日额度持久化开关 | `config/settings.py:488` | `runtime_daily_spend_persist: bool = True`；生产强制为 true（`settings.py:558-560`，`config/production_gates.py:46`） |
| nonce 防重放 / 幂等回放 | `services/runtime_nonce_log.py` | 落库 `RuntimeNonceLogModel`，一次请求一行（`in_flight`→`done`），重发原样回放首次响应；死占位可被接手（`STALE_IN_FLIGHT_SECONDS=120`） |
| 运行刹车 | `services/runtime_safety.py` + `RuntimeSafetyModeModel`（迁移 0060） | `assert_runtime_operation_allowed()` 同步快路径，散落所有动钱路由 |
| 交易幂等 | `services/trade_order_idempotency.py` | `Idempotency-Key` → `TradeOrderModel.launch_idempotency_key`；同键不同买/卖/需求 → 409 |

### 1.4 身份 / 认证 / 授权

- `api/middleware/auth.py`：JWT（HS256，15min，支持 `settings.secret_rotation_active()` 双钥验签）+ `X-Karma-Api-Key`（`karma_{agent_id}_{secret}`）；dev 回落头仅在 `AUTH_ENFORCE_PROTECTED_ROUTES` 关时生效。
- `services/runtime_key_service.py`：
  - `ALLOWED_PERMISSIONS = {request_voucher, verify_voucher, submit_receipt, update_progress, request_settlement, sync_task_status, discover_agents, place_order}`
  - `NONCE_REQUIRED_PERMISSIONS = {place_order, request_settlement}`；`MAX_KEY_LIFETIME_DAYS=90`；`PENDING_KEY_BINDING="agent_pending"`（未绑公钥前动钱一律拒）；`AGENT_SIGNATURE_TOLERANCE_SECONDS=300`。
  - 签名校验后才记 nonce（`runtime_key_service.py:466-467`），错签不烧 nonce。
- `services/actor_guards.py`：三道 `require_*` 后端权威判定（前端只画入口，画错=多一个 403，不是多一道门）。

---

## 2. 可以直接复用的 API 和 SDK

**HTTP（Runtime Gateway，`api/routes/runtime_gateway.py`，prefix `/runtime`，25 端点）** —— MCP 工具的主要落点：
`create-key` / `revoke-key` / `list-keys` / `bind-key` / `confirm-bind-key` / `reject-bind-key` / `list-bind-requests` / `list-pending-binds` / `list-bound-keys` / `unbind-key` / `key-calls` / `list-notices` / `ack-notice` / `permissions` / `capacity` / `policy` / `discover` / `place-order` / `request-voucher` / `check-voucher` / `submit-receipt` / `update-progress` / `submit-bundle` / `request-settlement` / `task-status/{task_id}`。

**HTTP（业务域，可直接映射为目标工具）**：
- 身份认证：`/v1/identity/{id}/verification/*`、`/v1/identity/{id}/verification/face-activate`、`/v1/identity/{id}/kyc`、`/v1/auth/siwe/verify`
- Agent 连接：`/v1/agents/connect-challenge|connect|connect-from-template|one-click-connect|owner-connect|owner-revoke|mine`
- 授权：`/v1/identities/{id}/automation-policy`、`/runtime/policy`
- 交易：`/v1/trade/orders/*`、`/v1/payment-codes/*`、`/v1/payment-intents/*`、`/runtime/place-order`
- 证据 / 收据：`/v1/evidence/*`、`/v1/evidence/bundles`、`/v1/receipts/*`、`/v1/progress/*`
- 结算 / 退款 / 争议：`/v1/settlement/{task_id}/*`（`buyer-accept|buyer-reject|dispute|fail|auto-confirm|auto-arbitrate`、`/transitions`）、`/v1/escrow/{id}/*`
- 信誉：`/v1/reputation`、`/v1/reputation/{agent_id}`、`/v1/reputation/{agent_id}/rewards`、`/v1/settlement-reputation/*`
- 人工确认：`/v1/confirmations/sessions`、`/pending`、`/plan`、`/assert`、`/sessions/{id}/decide`
- 验证者网络：`/v1/verifiers/*`（12 端点）
- 争议仲裁：`/v1/arbitration/*`（15 端点）
- 风控（公开投影）：`POST /v1/risk/assess`、`GET /v1/responsibility/model/public-risk`、`GET /v1/standards/accept-fulfillment/sellers/{seller_id}/risk`

**SDK**：`packages/karma-sdk`（Python + TS）、`packages/sdk`（TS HTTP）、`packages/karma-runtime-sdk`（TS）、根 `sdk/runtime_client.py` / `sdk/openclaw_agent.py`。

**上游文档**：`openapi/karma-v1.yaml`、`openapi/karma-public-console-api.yaml`、`docs/API_REFERENCE.md`、`docs/runtime-key-guide.md`、`docs/AGENT_INTEGRATION.md`、`docs/INTEGRATIONS.md`、`docs/mcp-adapter-guide.md`。

---

## 3. 已有 MCP 能力及其缺口

**已有**：`karma-mcp`（9 工具，直连链上，含私钥）、`karma-openclaw`（65 工具，Runtime Key 模型）。

**缺口（相对总指令目标工具目录）**：

| 缺口 | 说明 |
|---|---|
| 统一入口 | 两个包各自为政；没有「通用 Karma MCP」单一入口 |
| 私钥模型 | `karma-mcp` 依赖 `KARMA_PRIVATE_KEY`，与总指令冲突 |
| 远程传输 | 两个包都只有 `stdio`；总指令要求远程优先评估 Streamable HTTP |
| Schema / 错误分类 | 无统一输入 Schema、错误分类、超时与安全日志规范 |
| 撤销 | 目标 `karma_revoke_authorization` 无对应 MCP 工具（后端 `/runtime/revoke-key` + `/v1/agents/owner-revoke` 存在） |
| 风险结果 | `karma_get_risk_result` 无对应工具（私有仓不可验证） |
| 测试 | `karma-mcp` **零测试**；`karma-openclaw` 有 13 个 |

### 3.1 目标工具名 → 现状映射表

| 目标工具 | 现状 | 后端落点 |
|---|---|---|
| `karma_connect` | 部分（`karma_pairing_*`） | `/v1/agents/connect*`、`/runtime/bind-key` |
| `karma_get_connection_status` | 有（`karma_pairing_local_status` / `karma_runtime_binding_status`） | `/runtime/list-bound-keys` |
| `karma_get_identity_status` | 部分（通过 identity 路由） | `/v1/identity/{id}/verification` |
| `karma_start_identity_verification` | 部分（Console 侧） | `/v1/identity/{id}/verification/provider/session`、`/face-activate` |
| `karma_request_authorization` | 部分（`karma_save_automation_policy`） | `/v1/identities/{id}/automation-policy`、`/runtime/create-key` |
| `karma_get_authorization_status` | 有（`karma_automation_status`） | `/runtime/policy`、`/runtime/permissions` |
| `karma_get_policy` | 有（`karma_get_automation_policy`） | `/runtime/policy` |
| `karma_update_authorization` | 缺（需新增薄工具） | `/runtime/create-key`（重建）/ 待后端 |
| `karma_revoke_authorization` | 缺（需新增薄工具） | `/runtime/revoke-key`、`/v1/agents/owner-revoke` |
| `karma_create_intent` | 部分 | `/v1/payment-intents`、`/v1/discovery/intent` |
| `karma_create_transaction` | 有（`karma_launch_trade_order`） | `/v1/trade/orders/launch`、`/runtime/place-order` |
| `karma_get_transaction_status` | 有（`karma_get_trade_order` / `karma_runtime_task_status`） | `/v1/trade/orders/{id}`、`/runtime/task-status/{id}` |
| `karma_confirm_transaction` | 部分（`karma_accept_payment_code` / `karma_settlement_buyer_accept`） | `/v1/confirmations/*`、`/v1/payment-codes/{id}/accept` |
| `karma_submit_evidence` | 有（`karma_submit_evidence_bundle`） | `/v1/evidence/bundles`、`/runtime/submit-bundle` |
| `karma_verify_evidence` | 有（`karma_submit_verification`） | `/v1/evidence/{id}/verify`、`/v1/delivery-verification/*` |
| `karma_get_receipt` | 有（`karma_submit_execution_receipt` / `karma_list_receipts_for_task`） | `/v1/receipts/*` |
| `karma_get_settlement_status` | 有（`karma_get_settlement`） | `/v1/settlement/{task_id}`、`/transitions` |
| `karma_request_refund` | 部分（dispute/escrow 路径） | `/v1/settlement/{task_id}/dispute`、`/v1/escrow/*` |
| `karma_open_dispute` | 有（`karma_bilateral_dispute`） | `/v1/settlement/{task_id}/dispute`、`/v1/arbitration/cases` |
| `karma_get_reputation` | 缺（需新增薄工具） | `/v1/reputation/{agent_id}` |
| `karma_get_risk_result` | 缺（私有仓） | 公开侧仅 `/v1/risk/assess`、`/v1/responsibility/model/public-risk` |

---

## 4. 身份、授权、交易、验证和结算的实际调用链

**身份 / 连接 / 授权**
Console/Agent 发起 `POST /v1/agents/connect-challenge` → `POST /v1/agents/connect`（或 `one-click-connect`）→ 主人批准后 `POST /runtime/create-key` 签发 `KRM_RT_…` → `POST /runtime/bind-key` 绑定 Agent Ed25519 公钥（`PENDING_KEY_BINDING="agent_pending"` 期间动钱一律拒）→ 每次动钱请求带 `X-Karma-Agent-Signature` / `X-Karma-Runtime-Timestamp` / `X-Karma-Runtime-Nonce`，`runtime_key_service.py:454-467` 验签后才记 nonce。

**交易（含幂等）**
`POST /runtime/place-order` 或 `POST /v1/trade/orders/launch`（带 `Idempotency-Key` 与 `client_nonce`）→ `_nonce_claim`（`runtime_gateway.py:1552`，落库幂等回放）→ `services/trade_order_pipeline.py` 建 `TradeOrderModel` + `VoucherModel` → 日额度 `try_reserve_daily_spend`（`runtime_gateway.py:1556`）→ 商家 `POST /v1/payment-codes/{id}/accept`。

**资金约束**
买方/卖方各自 `lock` → `KarmaBilateral.bind(buyerBillId, agentBillId, scopeHash)` → 两 Bill `MINTED→BOUND`（冻结）→ `BindingState.ACTIVE/PENDING`。链上不变量 `freeBalance+boundBalance==totalMintedByAddr`。

**交付验证**
`POST /runtime/submit-receipt`、`/runtime/update-progress`、`/runtime/submit-bundle` → `POST /v1/evidence/{id}/verify`、`POST /v1/delivery-verification/{id}/verify` → 买家 `POST /v1/delivery-verification/{id}/buyer-confirm`。

**结算 / 退款 / 争议**
`POST /runtime/request-settlement` 或 `POST /v1/settlement/{task_id}/buyer-accept|auto-confirm` → `services/settlement_transitions.py` 状态机迁移 → 链上 `settle` / `finalizeSettle`（Burn 两 Bill、释放 USDC）→ `services/settlement_cycle_guard.py` / `settlement_receipt_release_guard.py` 守条件。失败/超时/争议路径：`/dispute` → `/v1/arbitration/cases` → `/v1/verifiers/*`。

**信誉**
`POST /v1/settlement-reputation/attestations/seal` → `GET /v1/settlement-reputation/agents/{agent_id}/public-reputation`、`POST /v1/reputation/{agent_id}/pack`。

**人工确认**
`POST /v1/confirmations/plan` → `/v1/confirmations/sessions` → 主人 `POST /v1/confirmations/sessions/{id}/decide`；`services/human_confirmation_policy.py` / `human_not_present_policy.py`。

---

## 5. 公共仓库与私有仓库的职责边界

- `VISIBILITY_MAP.md` 定义：**公开域** = `karma-core/**`、`docs/**`（公开部分）、`openapi/**`、`.github/workflows/**`、`README.md`、`SECURITY.md`、`scripts/**`（公开包装）；**私有域** = 引擎 / 内部 admin / outreach / 策略文档，位于**私有仓**（例如 Karma2），不在本仓。
- 边界规则：公开文件不得引用 `internal-admin/`、`docs-private/`，不得含 `seller-leads.csv`、`PRIVATE_MIGRATION_INVENTORY` 等内部产物，不得含 `KARMA_API_TOKEN`、`USER_PRIVATE_KEY`、`DEPLOYER_PRIVATE_KEY` 等疑似密钥键名。
- 自动化：`scripts/visibility-guard.sh` + `.github/workflows/visibility-guard.yml`。
- **本轮无法验证的部分（明确列出，不猜测）**：私有仓 Karma2 在本机不存在（已检索用户目录与盘根）。因此以下内容**未经核实**：私有风险引擎与内部验证接口、内部风险评分 / 欺诈 / 争议 / 信誉算法、公私仓数据契约与事件同步、内部 admin 接口。`karma_get_risk_result` 对应的内部实现**无法在此环境验证**。

---

## 6. 需要新增的模块、接口和数据模型

**新增（薄接入层，不重写业务）**
- `packages/karma-mcp-server`（暂名）统一 MCP Server：`stdio` + Streamable HTTP 双传输；只注入 `KARMA_RUNTIME_KEY`，**不注入私钥**；转发到 Runtime Gateway 与 `/v1/*`。
- 目标工具目录中缺失的薄工具：`karma_connect`（包装 `karma_pairing_*`）、`karma_get_identity_status`、`karma_start_identity_verification`、`karma_update_authorization`、`karma_revoke_authorization`、`karma_get_reputation`、`karma_get_risk_result`（公开投影版）。
- 统一层：输入 Schema、参数校验、错误分类（`auth` / `policy` / `limit` / `state` / `risk` / `transport`）、超时、安全日志（脱敏，凭证不入日志）。

**接口（优先复用，必要时才新增）**
- 首选复用 `/runtime/*` 与现有 `/v1/*`。
- 仅在无对应后端时新增：授权「更新」（当前只有 create/revoke）、授权「策略版本」语义。

**数据模型**
- 首选复用：`RuntimeKeyModel`（权限集 / single_limit / daily_limit / 过期）、`RuntimeNonceLogModel`、`RuntimeKeyDailySpendModel`、`TradeOrderModel`、`VoucherModel`。
- 可能新增：MCP 会话绑定表（`mcp_session`：client ↔ agent ↔ runtime_key ↔ identity 映射，仅存标识，不存密钥）。
- **授权策略修改（非缺口，设计选择）**：铸造 `POST /runtime/create-key` 已强制钱包签名锚定额度与边界（`services/runtime_wallet.py:39-68`）；「改额度」走「铸新 key + 注销旧 key」，无需新增接口。适用范围与红线见 §7.1。
- **聊天侧签名下发（缺口）**：签名链接 / 二维码 + 一次性 nonce + 短 TTL 的下发能力，见 §7.1-C2。

---

## 7. 潜在安全漏洞及兼容性风险

**P0 — 必须修**
1. **私钥进 MCP 进程**：`packages/karma-mcp/karma_mcp/chain.py:130` 与 `README.md:19/82/95`、`server.py:6/59/326`。违反总指令红线。修法：改为 Runtime Key / 网关代签（`karma-openclaw` 已是正确样板）。
2. **`karma-mcp` 零测试**：直连链上、可 lock/bind/settle，却没有任何测试覆盖。

**P1 — 需核实/补强**
3. **双套 nonce 实现**：`services/runtime_key_service.py:67-69` 的进程内 `_replay` / `_DAILY`（注释自承「single worker — use Redis in multi-instance」）与落库版 `services/runtime_nonce_log.py` / `services/runtime_daily_spend.py` 并存。当前 `deploy/Dockerfile.api:25` 与 `deploy/docker-compose.yml:69` 都是 `--workers 1`，故进程内实现当前不致漏；但一旦横向扩容，必须确认活跃路径已完全切到落库版。
4. **`karma_get_risk_result` 越界风险**：内部风控不得暴露给 MCP 客户端；只能暴露 `/v1/*` 公开投影。
5. **传输鉴权**：现有 MCP 只有 `stdio`（本地隐式可信）。远程必须补标准化身份验证与授权后方可开放。

**P2 — 兼容性 / 一致性**
6. **license 口径不一致**：根 `LICENSE` 为 AGPL-3.0；`packages/karma-openclaw/pyproject.toml:11` 写 Apache-2.0、README 写 AGPL-3.0-only、`packages/karma-mcp/pyproject.toml:10` 写 MIT。新包需澄清。
7. **MCP SDK 版本**：`pyproject.toml` 依赖 `mcp>=1.8.0,<2`，pin 到 v1 FastMCP（v2 会改名 `MCPServer`）。需与客户端兼容性一起评估。
8. **`NonCustodialAgentPayment` / `SettlementEngine` 口径**：总指令引用的是废弃路径；实现时须以 `KarmaBilateral` 为准，避免文档误导。

### 7.1 钱包签名的适用范围与安全边界（安全第一）

**总原则**：私钥永不离开用户设备；服务器与 LLM 都不得接触私钥、助记词或原始长期签名凭证。钱包签名只解决「证明某人控制某把钥匙」，**不解决「证明是本人」**——二者必须分开，混用即为资金安全事故。

**A. 可由钱包签名承担（当前已实现）**

| 步骤 | 现状 | 证据 |
|---|---|---|
| 交易启动授权（EIP-712 TradeLaunchIntent） | 已实现 | `services/trade_launch_eip712.py`、`services/trade_launch_signing.py:102`（preview）/:327（verify）、`api/routes/trade.py:158`（signing-preview）→ 钱包签 → `:121`（launch 带 `buyer_signature`） |
| 凭证授权（AuthorizationVoucher） | 已实现（`VOUCHER_REQUIRE_EIP712`） | `services/voucher_buyer_commitment.py:21` |
| 授权策略锚定（额度 / 权限 / 有效期 / agent 绑定） | 已实现（铸造即验签） | `services/runtime_wallet.py:39-68`（消息）、`:23-36`（验签）、`api/routes/runtime_gateway.py:405-474` |
| 交付证明 / 买家结算确认 | 已实现（EIP-712） | `docs/wallet-signature-payload-examples.json`（`DeliveryAttestation` / `SettlementConfirmation`） |
| 登录 / 身份关联（SIWE） | 已实现 | `apps/console/scripts/console-wallet-auth.js:15-22`、`POST /v1/auth/siwe/verify` |
| 手机钱包唤起（深链） | Console 已实现 | `console-wallet-auth.js:22`「手机钱包：唤起 App 打开本页」 |
| 私钥留在客户端 | 已实现 | `sdk/signing_backend.py`（`client_only` = 服务器不接触私钥） |

**B. 不可由钱包签名替代（必须保持独立）**

| 步骤 | 为什么 | 证据 |
|---|---|---|
| 同人核验 / KYC（刷脸） | 签名只证明钥匙，不证明是本人——这正是「更换钱包地址须本人刷脸」的根据 | `POST /v1/identity/{identity_id}/verification/face-activate`、`POST /v1/identity/role-profiles/{profile_id}/face-consistency` |
| 运行刹车 / 紧急冻结 | 运营侧安全控制，与用户签名无关 | `services/runtime_safety.py`、`POST /v1/admin/controls/emergency-freeze` |
| 风控判定 | 必须服务端权威判定，不得由客户端签名左右 | `services/actor_guards.py`、`/v1/risk/assess`（公开投影） |

**C. 当前缺口（须在 P2/P4 设计并落地）**

1. **授权额度 / 边界权限的钱包锚定——已实现（此前判断有误，据此更正）**：铸造 Runtime Key 的 `POST /runtime/create-key` **强制要求** `wallet_signature`（`CreateRuntimeKeyBody.wallet_signature`，`api/routes/runtime_gateway.py:408`），签名消息由 `build_create_key_message`（`services/runtime_wallet.py:39-68`）构造，**覆盖 `permissions` / `single_limit` / `daily_limit` / `expire_time` / `agent_binding`** 等全部授权边界；`verify_personal_message`（`services/runtime_wallet.py:23-36`）恢复签名人并要求与身份绑定钱包一致，不一致直接 403。即：**额度与边界权限本来就是钱包签的**。剩余缺口仅为「无原地修改入口」——改额度 = 铸新 key（重新钱包签名）+ 注销旧 key，符合安全预期，无需新增。
2. **非浏览器场景的签名下发**：Telegram / 微信等聊天窗口无法直接唤起钱包，需要「签名链接 / 二维码 + 一次性 nonce + 短 TTL」的下发能力。Console 深链已有，聊天侧为**新做**（P6）。
3. **签名重放的强制约束**：钱包签名必须绑定一次性 `launch_nonce` + `deadline` + `chain_id` / `verifying_contract`；服务端必须校验 nonce 未用过、未过期、与请求体指纹一致，**不得只依赖客户端**。已有机制见 `services/runtime_nonce_log.py`、`services/trade_launch_signing.py:27`；P4 须逐一验证覆盖。

**D. 安全红线（实现期不得违反）**

- MCP / Agent 进程环境变量只注入 `KARMA_RUNTIME_KEY`，**不注入**私钥或助记词（`docs/mcp-adapter-guide.md:5`）。
- 生产必须 `TRADE_LAUNCH_REQUIRE_EIP712=true`、`RUNTIME_REQUIRE_WALLET_IDENTITY_BINDING=true`、`KARMA_SIGNING_BACKEND=client_only|external`（禁 `local` / `env`）—— `config/production_gates.py:45,48`、`config/settings.py:669`。
- 签名只在客户端产生；服务端只**验签**，不代签（`POST /v1/trade/orders/launch/sign-with-backend` 仅 dev/CI，**禁止**对公网暴露）。
- 钱包签名不授予任何额度；额度仍由后端 Runtime Key 策略权威判定，动钱一律过后端复核（§4、§7）。

---

## 8. 测试覆盖情况

- 全量：`tests/` 共 **240** 个 `test_*.py`（`unit` 186 / `integration` 37 / `test_karma_billing` 6 / `test_verifier_network` 4 / `test_karma_security` 1）。
- 与本方案强相关、**已存在**：
  - `tests/unit/test_runtime_nonce_idempotency.py`（重放 / 幂等回放）
  - `tests/unit/test_runtime_daily_spend.py`（日额度落库）
  - `tests/unit/test_atomic_ledger_concurrency.py`（并发原子记账）
  - `tests/integration/test_trade_pipeline_idempotency.py`（交易幂等）
  - `tests/unit/test_runtime_key_signing.py`、`test_runtime_agent_binding_gate.py`、`test_runtime_agent_autonomy.py`
  - `tests/unit/test_auth_security.py`、`test_security_attack_mitigations.py`、`test_security_control_plane.py`
  - `tests/integration/test_automation_authorization_chain.py`、`test_runtime_e2e.py`、`test_p0_security_mode_dispute_e2e.py`
- `packages/karma-openclaw/tests/` 13 个（`test_guard.py` / `test_pairing_mcp.py` / `test_agent_binding.py` 等）。
- `packages/karma-connect` 3 个、`packages/karma-openmanus` 2 个、`packages/karma-a2a-bridge` 7 个。
- `packages/karma-mcp`：**0**。
- 验收脚本：`scripts/acceptance/`（`adversarial_fullchain_suite.py`、`adversarial_whole_project_suite.py`、`full_chain_audit_gate.sh`、`real_commerce_scenario_loop.py`、`public_testnet_preflight.sh` 等）。
- CI：`.github/workflows/` 9 个（`python-tests.yml` 跑正序 + **逆序**两遍 + 对抗套件 + 全链路审计门；`security-ci.yml`、`security-baseline-guard.yml`、`visibility-guard.yml`、`forge-ci.yml`、`deploy-vps.yml`、`deploy-fly.yml`、`pages-portal.yml`、`pr-migration-impact.yml`）。
- **本阶段未执行任何测试**（只读）。上述为覆盖现状盘点，非「已验证通过」。

---

## 9. 分阶段实施计划

遵循总指令「先复用现有系统，再建设通用 MCP；先证明授权安全，再开放资金操作；先完成可验证的端到端测试，再接入更多平台」。

- **P2 设计**：输出 `docs/mcp/karma-mcp-architecture.md` / `-tools.md` / `-security.md`；确认传输（stdio + Streamable HTTP）、鉴权、错误语义、工具开放顺序与权限等级。**先设计后实现。**
- **P3 接入/认证/授权**：`karma_connect` / 身份状态 / `karma_request_authorization` / `update` / `revoke`；自然语言 → 结构化策略预览 → 用户确认 → 后端持久化（**不得直接执行**）。
- **P4 强制授权检查**：每次动钱调用后端复核身份 / 绑定 / 有效期 / 范围 / 单笔 / 累计 / 对象 / 是否需二次确认 / 风控 / 状态机。并发额度走 `try_reserve_daily_spend`（落库原子）。
- **P4.1 钱包签名范围**：按 §7.1 执行——可签的（交易启动 / 凭证 / 交付 / 结算确认 / SIWE）走客户端签 + 服务端验签；不可签的（刷脸 / 刹车 / 风控）保持独立；重放约束逐一核验。
- **P5 复用真实闭环**：映射到 `KarmaBilateral` + `TradeOrder`/`Voucher`/`Settlement` 状态机；缺口单列，不伪造成功。
- **P6 跨平台**：先一个原生 MCP 客户端跑通全流程，再 OpenClaw → 桌面 Agent → Web → Telegram / 微信适配器（适配器不存私钥、不把聊天账号当资金凭证）。
- **P7 测试与验收**：新增可自动运行的功能 / 安全 / 交易测试，报告**真实执行结果**；测试网测试资产与账户；**未经单独批准不得主网真实资金交易**。

---

## 10. 每个判断的代码 / 测试证据

| 判断 | 证据 |
|---|---|
| `karma-mcp` 私钥进进程 | `packages/karma-mcp/karma_mcp/chain.py:130`、`server.py:6/59/326`、`README.md:19/82/95` |
| `karma-mcp` 无测试 | `packages/karma-mcp/` 下无 `tests/`（仅 3 个源文件 + `pyproject.toml` + `README.md`） |
| `karma-openclaw` 65 工具 | `p0_tools.py`/`phase1_tools.py`/`server.py`/`bilateral_tools.py`/`phase2_tools.py` 的 `@mcp.tool()` 计数 58 + `pairing_tools.py:540-543` + `runtime_tools.py:190-192` |
| Runtime Key 权限集 / 90 天 / pending 拒付 | `services/runtime_key_service.py`（`ALLOWED_PERMISSIONS` / `MAX_KEY_LIFETIME_DAYS` / `PENDING_KEY_BINDING`） |
| 签名后才记 nonce | `services/runtime_key_service.py:454-467` |
| nonce 落库幂等回放 | `services/runtime_nonce_log.py`、`api/routes/runtime_gateway.py:122/136/1552`、`tests/unit/test_runtime_nonce_idempotency.py` |
| 日额度原子占额 + 落库 | `services/runtime_daily_spend.py:23/78/141`、`api/routes/runtime_gateway.py:124-128/1556`、`config/settings.py:488`、`tests/unit/test_runtime_daily_spend.py` |
| 原子记账守卫式 UPDATE | `services/atomic_ledger.py`、`tests/unit/test_atomic_ledger_concurrency.py` |
| 交易幂等 | `services/trade_order_idempotency.py`、`tests/integration/test_trade_pipeline_idempotency.py` |
| 链上状态机 + 不变量 | `karma-core/contracts/core/KarmaBilateral.sol:47/109-121` |
| 单 worker | `deploy/Dockerfile.api:25`、`deploy/docker-compose.yml:69` |
| 公私边界 | `VISIBILITY_MAP.md`、`.github/workflows/visibility-guard.yml`、`scripts/visibility-guard.sh` |
| 授权策略由钱包签名锚定 | `api/routes/runtime_gateway.py:405-474`、`services/runtime_wallet.py:23-68` |
| 活跃支付路径是 Bilateral | `README.md`（`NonCustodialAgentPayment` 为废弃口径） |
| CI 正序 + 逆序 + 对抗 + 全链路门 | `.github/workflows/python-tests.yml` |
| MCP 接入红线（不注入私钥等） | `docs/mcp-adapter-guide.md:5-9` |
| Runtime Gateway 25 端点 | `api/routes/runtime_gateway.py`、`work/_routes.txt` |
| license 口径不一致 | 根 `LICENSE`（AGPL-3.0）vs `packages/karma-openclaw/pyproject.toml:11`（Apache-2.0）vs `packages/karma-mcp/pyproject.toml:10`（MIT） |

---

## 11. 未完成 / 无法验证项（不猜测）

1. 私有仓 Karma2 全部内容（本机不存在）。→ `karma_get_risk_result` 的内部实现无法验证。
2. 未执行任何测试 / CI / 部署（本阶段只读）。
3. `runtime_key_service.py` 进程内 `_replay` / `_DAILY` 是否在所有活跃路径上已被落库版取代 —— 需在 P4 逐一核对调用点。
4. `karma_get_risk_result`、`karma_update_authorization` 是否需要新增后端接口 —— 待 P2 设计与后端确认。

---

**本报告为第一阶段交付物。按要求：审计到此停止，等待批准后再进入第二阶段设计；在此之前不修改核心代码、不提交、不部署。**