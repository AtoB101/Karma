# Karma 通用 Agent MCP Server —— 架构设计（第二阶段 · P2）

> 上游依据：`docs/mcp/karma-mcp-audit.md`（第一阶段审计，已批准）。
> 本文件只做**设计**；实现按本报「实施顺序」逐层落地，先设计后编码。

---

## 1. 定位与原则

- **Any Agent. Any Interface. One Trust Layer.** MCP 是统一接入接口，不是新的身份系统、支付系统或独立结算系统。
- **薄接入层**：MCP Server 只做「翻译 + 转发 + 校验」，所有身份、授权、风控、状态机、结算判定都在 Karma 后端。
- **先复用现有系统，再建设通用 MCP。**
- **先证明授权安全，再开放资金操作。**
- **一票否决**：任何工具调用成功，都不等于交易成功。资金是否真的动，只听后端的。

## 2. 组件与分层

```
 ┌────────────┐   MCP (stdio / Streamable HTTP)   ┌────────────────────┐
 │ 用户 Agent │ ────────────────────────────────► │ Karma MCP Server   │
 │ 聊天窗口   │ ◄──────────────────────────────── │ (薄接入层, 无业务) │
 └────────────┘                                   └─────────┬──────────┘
                                                            │ HTTPS + Runtime Key + Agent 签名
                                                            ▼
                                      ┌──────────────────────────────────────┐
                                      │ Karma 后端 (权威)                     │
                                      │  /runtime/*  ·  /v1/*                 │
                                      │  身份·授权·风控·状态机·结算·信誉·仲裁 │
                                      └──────────────────────────────────────┘
```

MCP Server 内部四层，自上而下：

| 层 | 职责 | 不做什么 |
|---|---|---|
| L1 传输层 | stdio / Streamable HTTP；会话与连接生命周期 | 不做业务判定 |
| L2 工具层 | 输入 Schema、参数校验、错误分类、超时、审计日志 | 不直接碰链、不碰私钥 |
| L3 策略前置层 | 只做「本地可见」的快速拒绝（未配对、权限不含该动作），**权威判定仍交后端** | 不做最终放行 |
| L4 后端客户端 | 注入 `X-Karma-Runtime-Key` + 逐请求 Agent 签名 + `client_nonce`；转发 `/runtime/*` 与 `/v1/*` | 不代签钱包交易、不持有私钥 |

**关键约束**：L3 的判定是「优化」，不是「安全门」。安全门只有一个 —— 后端 `services/actor_guards.py` + `/runtime/*` 的权限与额度校验（审计 §1.4）。

## 3. 传输

| 场景 | 传输 | 说明 |
|---|---|---|
| 本地桌面 Agent（OpenClaw 等） | `stdio` | 与现有 `karma-openclaw` 一致 |
| 远程 / 多客户端 | **Streamable HTTP** | 远程**必须**叠加标准化身份验证与授权后才可开放（见 §6） |
| 聊天平台（Telegram / 微信） | 不直连 | 走可信适配器调用后端；适配器不存私钥、不把聊天账号当资金凭证 |

MCP SDK 版本：`mcp>=1.8.0,<2`（pin 到 v1 FastMCP；v2 会改名 `MCPServer`，升级需单独评估）。

## 4. 身份模型（三层，缺一不可）

| 层 | 是什么 | 谁签发 | 存哪 |
|---|---|---|---|
| 用户身份 | Karma Identity（含刷脸/KYC 与绑定钱包） | 后端 | 后端 |
| 授权凭证 | **Runtime Key** `KRM_RT_…`（权限集 + 单笔/日额度 + 有效期 + agent 绑定） | 后端，铸造时**要求主人钱包签名** | Agent 侧凭据文件；MCP 进程环境变量 |
| Agent 身份 | Agent Ed25519 公钥（绑定后逐请求签名） | Avatar/Agent | 私钥在 Agent 本地，公钥钉在 key 上 |

**要点**：Runtime Key 的额度与边界**本身就是主人钱包签名的对象**（`services/runtime_wallet.py:39-68` 覆盖 `permissions`/`single_limit`/`daily_limit`/`expire_time`/`agent_binding`）。所以「授权需签名」这一步不需要重新发明 —— 那就是铸造 key 的那一刻。

**凭据规则**：
- MCP 进程环境变量**只**注入 `KARMA_RUNTIME_KEY`；**禁止**注入私钥、助记词、`USER_PRIVATE_KEY`、`DEPLOYER_PRIVATE_KEY`（`docs/mcp-adapter-guide.md:5`）。
- Agent 签名私钥留在 Agent 本地（`~/.karma/agent.env` 0600，只回指纹）。
- 未绑公钥的 key 处于 `agent_pending`，动钱一律 403（`services/runtime_key_service.py` 的 `PENDING_KEY_BINDING`）。

## 5. 请求流

### 5.1 读（无副作用）
`工具 → L4 GET /runtime/* | /v1/* → 返回`。读路径不落调用记录、不发 `client_nonce`。

### 5.2 写（有副作用，且不碰钱）
如 `update-progress`。必须带 `client_nonce`（≥8 字符），后端做落库幂等回放。

### 5.3 动钱（最高等级）
`place-order` / `request-voucher` / `request-settlement` 一律：
1. L3 快速拒绝（无 Runtime Key / 权限不含该动作）；
2. 后端 `get_runtime_context` → 激活检查 → Agent 逐请求验签 → 按 key 限速；
3. 后端 `assert_permission` → `client_nonce` 落库占位 → 单笔/日额度校验/原子占额；
4. 业务状态机推进；**成交与否由后端与链上决定**。

**映射**：每一步都对应后端已有实现（审计 §4），MCP 不新增任何资金语义。

## 6. 会话与连接

- `karma_connect` = **配对**，不是身份认证。方向固定：Agent 出 `user_code` → 主人在 Console 输码/扫码批准 → 凭据落 Agent 侧。
- 配对成功**不授予任何资金权限**；资金权限只在 key 上，且 key 由主人钱包签名铸造。
- 未配对 = 只能调 `karma_connect` / `karma_get_connection_status`。

## 7. 幂等、重放与并发额度（安全核心）

| 关注点 | 机制 | 证据 |
|---|---|---|
| 请求重放 | `client_nonce` 落库，一次请求一行（`in_flight`→`done`），重发**原样回放**首次响应；同 nonce 换请求体 → 拒 | `services/runtime_nonce_log.py` |
| 交易重复创建 | `Idempotency-Key` → `TradeOrderModel.launch_idempotency_key`；同键不同买卖/需求 → 409 | `services/trade_order_idempotency.py` |
| 累计额度并发 | 守卫式单条 UPDATE 原子占额，`rowcount==0` 即拒 | `services/runtime_daily_spend.py:78-135` |
| 账本并发 | 守卫式原子加减（相对增量，禁止绝对赋值） | `services/atomic_ledger.py` |

MCP 层**不得**自行实现这些；必须传 `client_nonce` / `Idempotency-Key` 让后端做。

## 8. 错误分类（统一返回给客户端）

| 分类 | 含义 | 客户端该怎么办 |
|---|---|---|
| `transport` | 连不上后端 / 超时 | 可重试（写操作必须带幂等键） |
| `unauthorized` | 无 key / key 无效 / 验签失败 | 重新 `karma_connect` |
| `not_activated` | key 已铸但未被 Agent 激活（`agent_pending`） | 引导主人在 Console 输配对码 |
| `forbidden` | key 有权限，但**边界**不允许（超额度 / 不在范围 / 状态机不允许） | 不得重试，向用户解释 |
| `conflict` | 同 nonce/键换了内容；重复交易 | 不得重试，需新 nonce |
| `rate_limited` | 触达按 key 的写限速 | 退避重试 |
| `invalid` | 参数校验失败 | 修正参数，不得重试 |
| `backend` | 后端 5xx | 保守重试（写操作必须幂等） |

**铁律**：错误**不得**被转换成成功。任何失败默认拒绝。

## 9. 超时与重试

- 读：超时 30s，可重试。
- 写 / 动钱：超时 120s，**只**在带幂等键（`client_nonce` / `Idempotency-Key`）时重试，且重试必须复用同一键。

## 10. 目标目录结构（新包）

```
packages/karma-mcp-server/
  pyproject.toml                 # mcp>=1.8,<2 · httpx · cryptography
  README.md
  karma_mcp_server/
    __init__.py
    __main__.py                  # 入口，按 --transport 选择 stdio / http（含三道启动红线）
    config.py                    # Tier / HTTP / URL 配置（T2/T3 默认关）
    credentials.py               # 凭据文件读取（只读，绝不回显）+ 私钥注入检查
    credential_store.py          # 凭据/配对状态写入（0600 原子落盘）
    redact.py                    # 指纹与钱包地址脱敏
    agent_signing.py             # Agent Ed25519 逐请求签名（与服务端逐字对齐）
    wallet_messages.py           # 钱包待签文案（与 runtime_wallet 逐字对齐，绝不代签）
    pairing.py                   # 配对状态（只落本机，不进聊天）
    http_auth.py                 # 远程静态 bearer token 校验 + AuthSettings
    backend_client.py            # L4：注入 header、nonce、超时、错误分类
    errors.py                    # 错误分类码
    server.py                    # FastMCP 实例 + 工具注册（按 Tier 白名单 fail-closed）
  tests/
```

**与既有包的关系**：`packages/karma-openclaw` 是**正确样板**（Runtime Key 模型、配对方向、guard）；本包把它的可复用做法收敛为通用入口。`packages/karma-mcp` 的**私钥进进程**模型作废（审计 §7-P0），不作为基础。

## 11. 实施顺序（先设计后编码）

| 步 | 内容 | 产出 | 状态 |
|---|---|---|---|
| S1 | 本设计三件套（architecture / tools / security） | 设计文档 | 已完成 |
| S2 | 包骨架：config / credentials / agent_signing / backend_client / errors / server（stdio） | 可跑的薄层 | 已完成 |
| S3 | 配对 + Tier-0/1 工具（连接、身份、授权状态、授权读写/撤销） | 只读 + 授权 | 已完成 |
| S4 | Streamable HTTP 传输 + 远程鉴权（静态 bearer token） | 远程入口 | 已完成（OAuth 2.1 待后续） |
| S5 | Tier-2/3 工具（交易 / 证据 / 结算），每次调用强制后端复核 | 交易闭环 | 工具已注册（默认关）；真实资金 E2E 未跑 |
| S6 | 跨平台适配器（Telegram / 微信等） | 适配说明 + 适配器 | 未开始 |

S2–S5 属第二阶段（本轮交付）；S6 属第三阶段及以后。Tier-2/3 的**真实资金端到端**必须在
测试环境用测试资产跑通后才算验收（安全 §9），当前仅验证工具注册与后端转发。

## 12. 明确不做（本阶段）

- 不重写核心业务逻辑（身份、支付、结算、风控、状态机）。
- 不把私钥、助记词、原始长期签名凭证交给 LLM 或 MCP 进程。
- 不在 MCP 层实现额度/风控/状态机判定。
- 不用 Mock / 硬编码冒充真实交易闭环。
- 不暴露内部风控接口（私有域，见审计 §5）。
