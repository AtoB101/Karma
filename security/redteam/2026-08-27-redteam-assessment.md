# Karma Red Team Assessment — 2026-08-27

> 攻击者视角评估。范围：KarmaBilateral 合约（`karma-core/contracts/core/KarmaBilateral.sol`）、
> 部署脚本、后端资金状态机 API、认证中间件、仲裁链路、热钱包签名路径。
> 结论基于对真实代码的静态审计 + 攻击路径推演，未做动态渗透测试。

## 0. 执行摘要

**总体判断：可以攻破，但不在合约资金路径上，而在三个密钥/凭据信任根 + 经济层。**

- 合约 escrow 设计（无 admin 提款函数 + 全状态超时 + 双不变量 + reentrancy 防护）没有发现可"凭空提取锁定资金"的链上漏洞。
- 系统的真实信任全部押在 3 个密钥/凭据上：`APP_SECRET_KEY`（JWT 信任根）、仲裁员会话凭据、admin 多签。
- 这三个东西的强度，Solidity 保证不了。攻击者最优解是打密钥，不是打合约。
- 另发现 1 个记账语义问题（`accept()` 幽灵余额，中危，非资金漏洞）和 1 类经济攻击组合。

## 1. 攻击路径总览

| # | 攻击向量 | 前置条件 | 后果 | 评级 |
|---|---|---|---|---|
| A1 | `APP_SECRET_KEY` 泄露/弱密钥 → 伪造 JWT | 拿到或猜出 secret | 任意 agent_id → 伪 admin → 改安全模式/调仲裁 | **P0-严重** |
| A2 | 仲裁员凭据被盗 → `/disputes/resolve` | 白名单 actor 的会话/API key | 大额争议判给攻击方 | **P0-严重** |
| A3 | admin 多签单点 → feeBridge 吸血 | admin 私钥或 1/1 多签 | 每笔 settle 抽 10% | **P1-高危** |
| A4 | Sybil 刷分 → 高信誉骗局 | 注册多身份互相对敲 | 信任体系瓦解 | P1-高危 |
| A5 | 争议滥用/粉尘锁款 | 少量资金 + 时间 | DoS 拖死小 agent | P2-中危 |
| A6 | `accept()` 幽灵余额 | 任意地址 | 记账污染，未来功能误用风险 | P2-中危 |
| A7 | TEE/ZK 结算绕过 | Phase 2/3 实现 | 跳过 dispute window 即时结算 | 未实现·预留 |

## 2. 逐条攻击路径

### A1. `APP_SECRET_KEY` — JWT 信任根（P0-严重）

**代码依据**：`api/middleware/auth.py:39` — HS256 签发/验签全部依赖 `settings.app_secret_key`。

**攻击方式**：
1. 拿到 `APP_SECRET_KEY`（CI 日志、容器镜像 env、`.env` 泄露、弱密钥爆破）。
2. 伪造任意 `agent_id` 的 JWT：`jwt.encode({"sub": "<admin_actor_id>", "exp": ...}, secret, algorithm="HS256")`。
3. 若伪造的是 admin 白名单 ID → 直接调 `/v1/admin/controls/safety-mode`（`api/routes/admin_controls.py:59` 只校验 agent_id ∈ `admin_actor_id_set`）。
4. 或伪造买卖双方 agent_id → 自由操纵订单/争议状态机。

**为什么这是最优路径**：JWT 是整个后端 API 的唯一信任根，一次泄露即全量身份伪造。没有额外的 nonce/设备绑定/二次认证。

**现状缓解**：无（依赖部署时 secret 强度与环境隔离）。

**建议**：
- P0：将 `APP_SECRET_KEY` 移入 KMS/密钥管理服务，禁止明文出现在 env 文件。
- P1：admin 控制操作叠加二次校验（独立 admin API key 或 step-up 认证）。
- P1：增加 `admin 操作审计`（本轮已落地的缓解项，见 §5）。

### A2. 仲裁员凭据 → 劫持争议（P0-严重）

**代码依据**：`api/routes/telegram_miniapp_commerce.py:684` `/disputes/resolve`，鉴权 `_require_arbitrator`（33-56 行）依赖：
- Telegram 登录会话（bearer token）
- 或 `sess.telegram_user_id` ∈ `ARBITRATOR_ACTOR_IDS`

**攻击方式**：
1. 窃取白名单仲裁员的 Telegram 会话 token（会话劫持、Telegram 端入侵）。
2. 调用 `/disputes/resolve`，把大额争议直接判 refund 或释放给攻击方。

**为什么严重**：这是少数能**直接决定资金归属**的 API。一旦凭据被盗，攻击方从"骗"变成"抢"。

**现状缓解**：白名单已封（P1-3 修复，生产强制非空）。但白名单内凭据被盗后无审计、无告警、无二次确认。

**建议**：
- P0：`/disputes/resolve` 增加审计事件 + 告警（本轮已落地）。
- P1：仲裁退款路径叠加独立确认（双人复核或 TOTP）。
- P1：`/disputes/resolve` 的大额 refund 强制走链上 `resolveDispute` 多签，禁止后端直接改状态。

### A3. admin 多签单点 → feeBridge 吸血（P1-高危）

**代码依据**：`karma-core/contracts/script/DeployKarmaBilateral.s.sol:82` mainnet guard 要求 admin/arbitrator 是合约地址；但 `admin` 在 KarmaBilateral 中 immutable，且具备 `setFeeBridge`/`setTokenAllowed` 等参数控制权。

**攻击方式**：
1. 若 admin 多签阈值是 1/N（或部署被绕过，admin 为 EOA），攻击方获取 admin 私钥。
2. 调用 `setFeeBridge` 指向攻击方合约，`quoteFee` 返回 10%。
3. 此后**每笔 settle 自动抽 10% 手续费**给攻击方合约（上限硬编码 10%，但 10%×总量已致命）。

**为什么不是直接提款**：合约**没有**"admin 提取用户锁定资金"的函数——这是设计优点。所以即使 admin 被攻破，用户 escrow 不会被直接抽空，只能通过 fee 渠道持续吸血。

**现状缓解**：mainnet guard（部署脚本级），多签阈值取决于部署配置。

**建议**：
- P0：多签阈值必须 N/N（或 2/3 以上），并在部署后固化。
- P1：`setFeeBridge` 增加 timelock（例如 48h 生效，给用户撤离窗口）。
- P1：fee 费率上限再压（10% 偏高），且每笔 fee 抽取必须发事件供监控。

### A4. Sybil 刷分（P1-高危）

**攻击方式**：注册多个 identity/agent（`KarmaIdentitySBT` 是可编程铸造还是需要验证？需审计 mint 权限），互相对敲虚拟任务，刷高 `ScoringEngine` 信誉，然后用高信誉身份骗取真实买家的 escrow。

**现状缓解**：需确认 SBT mint 是否有身份验证门槛。

**建议**：
- P1：SBT/identity 铸造必须有链上验证门槛（至少 gas 成本 + 人工/推荐制）。
- P1：新 agent 评分设置 cap，需真实履约量解锁。

### A5. 争议滥用 / 粉尘锁款（P2-中危）

**攻击方式**：
1. 作为买家反复 dispute（押 24h 锁定 + 证据成本），对资金薄的 agent 是持续 DoS。
2. 锁大量小额 bill 故意 bind 不 settle，占 `pendingBatchAmount`，干扰 batch 阈值触发。

**现状缓解**：dispute 需要锁定资金 + 证据；批量锁款有时间超时兜底。但攻击成本仍低。

**建议**：
- P2：dispute 增加手续费（gas + 小额押金），恶意 dispute 扣押金。
- P2：监控"高 dispute 率 / 高 lock 不履约率"作为 Sybil 组合信号。

### A6. `accept()` 幽灵余额（P2-中危，记账语义问题）

**代码依据**：`karma-core/contracts/core/KarmaBilateral.sol:983`（`accept()` 授权链路）——
`boundBalance[auth.from] += amount; freeBalance[auth.to] += amount; totalMintedByAddr[auth.to] += amount;`

**问题**：`authorize` 只要求 `from` 的 `freeBalance` 足够；`accept` 不要求 `from` 名下真有锁定资金支撑。结果是：
- `auth.to` 凭空多出一笔"幽灵 freeBalance"，`totalLockedByAddr[to]` 同步增加。
- 但 `to` 名下没有任何 Bill Token，**无法直接 unlock 提现**。
- 全球不变量 `totalBillSupply == totalLocked` 不破，per-address 记账被污染。

**为什么不是资金漏洞**：所有资金出口（settle/refund/unlock/split）都需要 Bill Token 或绑定，幽灵余额无法变现。

**风险敞口**：未来如果新增"余额直接付款"类功能，可能误用幽灵余额作为支付来源。

**建议**：
- P2：在 registry 登记该行为（本轮已登记），加不变量测试锁定"幽灵余额不可变现"。
- P2：未来改造 `accept` 校验 `from` 的 `boundBalance` 支撑，或拆分"可用余额"与"已锁定余额"记账。

### A7. TEE/ZK 结算绕过（未实现·预留）

**代码依据**：`settleWithTEE` / `settleWithZKProof` 目前是 `revert NotImplemented` stub。

**风险**：这两条路径一旦实现，有效证明 = 跳过 dispute window = 即时结算。这是"权限最大、资金流动最快"的出口。若证明校验（attestation 真实性 / ZK 电路正确性）有缺陷，等于给攻击者开了一扇即时提款门。

**建议**：
- P0（实现前）：TEE 路径必须验证 attestation 签名链 + 报告内容哈希绑定；ZK 路径必须电路形式化验证（Certora/Halmos）。
- 实现时登记 registry → 不变量测试 → 攻击矩阵追加 → 用户审核合并。

## 3. 资金出口盘点（已核实的 5 条出口）

| 出口 | 触发条件 | 谁能触发 | 风险 |
|---|---|---|---|
| settle / finalizeSettle | 履约证明 + dispute window 通过 | 任何人（状态机守卫） | 低 |
| refundOnTimeout | settle_timeout 到期 | 买家 | 低（全额退双方） |
| resolveDispute(auto) | 大额争议 + 仲裁结果 | admin 多签 | 中（依赖 admin 密钥） |
| unlock | 未绑定未结算 | owner | 低 |
| **后端 refund/结算** | API 状态机 | 后端服务（热钱包） | **中（依赖服务密钥）** |

> 注：真实环境中"后端服务密钥"其实是第 4 个信任根（热钱包 `TESTNET_PRIVATE_KEY` / x402 key）。
> 生产已要求 `CHAIN_ALLOW_HOT_WALLET_PAYER=false`，但密钥本身的强度仍是部署责任。

## 4. 信任根汇总（攻击者最想拿的 4 样东西）

| 信任根 | 拿到的后果 | 存放位置 | 现状 |
|---|---|---|---|
| `APP_SECRET_KEY` | 伪造任意身份 | 后端 env | 无 KMS |
| 仲裁员会话凭据 | 直接决定争议资金归属 | Telegram session / API key | 白名单已封，无审计 |
| admin 多签私钥 | feeBridge 吸血 10% | 签名者钱包 | 依赖多签阈值 |
| 后端热钱包 key | 直接发退款/结算交易 | 服务 env | 生产已禁 hot-wallet-payer |

## 5. 本轮已落地的缓解项（随本报告提交）

| 缓解项 | 文件 | 说明 |
|---|---|---|
| 仲裁操作审计事件 | `services/security_monitoring.py` | 新增 `ARBITRATOR_ACTION` 事件类型 |
| 管理员操作审计事件 | `services/security_monitoring.py` | 新增 `ADMIN_CONTROL_ACTION` 事件类型 |
| 审计埋点 | `api/routes/telegram_miniapp_commerce.py` | `/disputes/resolve` 成功调用后上报 |
| 审计埋点 | `api/routes/admin_controls.py` | `/controls/safety-mode`、`/controls/operational-pauses` 变更后上报 |
| 告警接入 | `services/security_monitoring.py` | 高敏感操作突增触发告警 + 推荐动作 |
| 登记表更新 | `security/registry/financial_functions.yaml` | 登记信任根 + `accept()` 幽灵余额发现 |

## 6. 未解决 / 待 Phase 2-5 覆盖

- 密钥轮换 SOP（KMS 化）
- admin/arbitrator 二次认证（step-up auth）
- 链上 Emergency Freeze（Phase 2）
- Security Control Plane 持久化审计（当前为内存环形缓冲，重启即丢）
- TEE/ZK 实现的正式验证
- Sybil 检测（SBT mint 门槛 + 组合信号监控）

## 7. 一句话结论

> **合约把钱锁得死死的；系统把钥匙挂在大门上。** 攻击 Karma 的正确姿势不是破解 escrow，
> 而是偷钥匙——`APP_SECRET_KEY` 一把钥匙开全部门，仲裁员凭据直接决定资金归属。
> 这两把锁不上保险，合约写得再稳也只是把保险箱放在透明玻璃后面。

---
*报告编号：KARMA-RT-2026-08-27-001 · 评估人：AI Red Team · 复核人：待用户审核*
