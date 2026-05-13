# Karma 神经网络系统 FINAL V1.0 工程开工蓝图（CN）

版本：v1.0（工程执行版）  
状态：可直接进入技术排期与实现  
适用仓库：`/workspace`（public repo）

---

## 1. 文档目标

本文件将《Karma 神经网络系统最终版开发设计细则（FINAL V1.0）》转成可执行工程方案，供合约、后端、SDK、前端团队同步开工。

交付目标：

1. 保留 FINAL V1.0 的核心铁律与责任模型。
2. 与当前仓库真实代码结构对齐，避免“概念名”和“工程名”错位。
3. 给出 P0 -> P3 的任务拆解、验收标准、测试与风险门槛。

---

## 2. 最高铁律（必须固化为不可回归约束）

1. `1 USDC lock == 1 Bill Credit`（严格 1:1）。
2. 禁止任何信用杠杆、授信垫付、部分准备金。
3. 责任状态总和必须始终锚定真实锁仓资产。
4. 任务开始前必须冻结额度，仲裁时不可出现余额不足。
5. Bill Credit 是内部责任记账单位，不是可交易代币。
6. 结算与同额销毁必须原子化（同一状态转换）。

建议落地为三类机制：

- 合约不可变约束（`require` + custom errors + invariants）。
- 服务端守卫（状态机校验 + 幂等 + 对账巡检）。
- CI/监控告警（账本守恒、异常状态迁移、余额偏差）。

---

## 3. 与当前仓库的“单一黄金路径”对齐

当前仓库已有明确约束：不要并行复制第二套结算权威合约。

参考：`contracts/README.md`  
当前核心合约源：`karma-core/contracts/core/`

- `NonCustodialAgentPayment.sol`（账单生命周期与非托管支付主路径）
- `SettlementEngine.sol`（EIP-712 报价结算）
- `AuthTokenManager.sol`（授权 token 消耗）
- `KYARegistry.sol`（身份/注册策略）
- `CircuitBreaker.sol`（熔断与紧急控制）

**执行约束：**

1. FINAL 文档中的模块名可作为“概念层”。
2. 工程实现必须映射到现有核心路径，不得复制一套新的结算主权。
3. 任何新增模块必须以“扩展”方式接入，不替代既有结算权威。

---

## 4. 概念模块 -> 工程映射（FINAL V1.0）

| FINAL 概念模块 | 当前工程落点 | 实施策略 |
|---|---|---|
| KarmaIdentitySBT | `KYARegistry.sol` + 新增 SBT 合约 | P0 新增 SBT 扩展，KYA 保持策略入口 |
| KarmaVault | `NonCustodialAgentPayment.sol` 资金锁定路径 | 不新增并行资金池，复用现有 escrow 逻辑 |
| KarmaBillLedger | 现有账单状态 + 新增 credit ledger（合约或服务） | 先服务端镜像账本，后链上增强 |
| KarmaVoucher | `AuthTokenManager.sol` + SDK 签名流 | 用 EIP-712 voucher 扩展现有授权模型 |
| KarmaTaskManager | `TaskStatus`/`settlement` 状态流 + API | 统一到标准状态机并补事件 |
| KarmaReceiptRegistry | `core/schemas.py` + `db/models/orm.py` + receipt APIs | 扩展 receipt 字段并链上锚定 hash |
| KarmaProgressManager | 新增 progress service + DB 表 | P1/P2 实施，支持 regret / partial |
| KarmaDisputeManager | dispute flow + arbitration adapter | P2 起建设，先自动规则后去中心化池 |
| KarmaSettlementEngine | `SettlementEngine.sol` + `core/settlement/engine.py` | 保持单路径，补“结算即销毁”约束 |

---

## 5. P0（必须先实现）— 最小责任闭环

### 5.1 合约层（P0）

1. 身份：实现不可转让 SBT（或在现有身份层加 soulbound 约束）。
2. 锁仓：确认 USDC 锁仓路径与额度占用完全对应。
3. 1:1：建立 `locked_usdc == total_bill_credits_active` 不变量。
4. Voucher：EIP-712 一次性授权 + 过期 + nonce 防重放。
5. 状态机：`Created -> Authorized -> Reserved -> Accepted -> InProgress -> Delivered -> Settled/Refunded` 的最小子集。
6. 结算：USDC 结算与 Bill Credit 销毁同一原子状态变化。

### 5.2 后端层（P0）

1. Identity service：身份索引与状态缓存。
2. Capacity service：可用/冻结/执行中额度计算。
3. Voucher service：签名校验、使用态校验、过期处理。
4. Task service：状态机统一校验（拒绝非法跃迁）。
5. Receipt service：Execution Receipt 接收、哈希入库、锚定字段输出。

### 5.3 SDK/前端（P0）

1. Buyer SDK：`lockUSDC`、`getCapacity`、`createVoucher`。
2. Seller SDK：`verifyVoucher`、`acceptTask`、`submitExecutionReceipt`。
3. Console：连接钱包、身份创建、锁仓、额度查看、Voucher 创建。
4. Seller Dashboard：Voucher 验证、接单、回执提交。

### 5.4 P0 验收门槛（必须全部通过）

1. 任务授权后可用额度即时下降，冻结额度即时上升。
2. 同一 voucher 二次使用被拒绝。
3. 无回执不能进入自动结算。
4. 争议触发时对应额度已冻结。
5. 每笔结算均存在同额销毁记录。
6. 全量守恒：`sum(active_credits) <= vault_balance_usdc`。

**仓库落地补充（与 §5.1–§5.3 对齐）：**

- Python `sdk.KarmaClient`：`lock_usdc`（`lock_capacity` 别名）、`create_settlement` / `mark_settlement_pending` / `lock_settlement`、`accept_task`（创建结算→pending→lock）、`submit_execution_receipt`（`POST /v1/receipts`）。
- EIP-712：`services/voucher_eip712.py`；运行时 `VOUCHER_REQUIRE_EIP712` / `voucher_eip712_chain_id` / `voucher_eip712_verifying_contract`（见 `config/settings.py`）；OpenAPI `CreateVoucherRequest` 含 `buyer_wallet_address`。
- **验收自动化**：`tests/integration/test_p0_acceptance.py`（§5.4 六条）；`tests/unit/test_voucher_eip712.py`。
- **操作端（与官网隔离）**：`examples/p0-buyer-seller-console.html`（配置 API Base URL；钱包仅在本页用于演示锁仓与签名）。
- **TypeScript SDK**：`packages/sdk`（`npm run build` 生成 `dist/`）。

---

## 6. P1 / P2 / P3 实施范围

### P1（回执标准化 + 进度责任）

1. 标准化 API/MCP/Agent Runtime 回执模板（`ExecutionReceipt.extension` + voucher `task_type` 前缀绑定；`sdk/execution_receipt_helpers.py`；Hook `run_tool(..., extension=)`；OpenAPI `POST /v1/receipts`）。
2. Progress Receipt + Confirmed Progress。
3. Buyer Regret 责任计算（含非线性价值曲线）。
4. 部分结算（partial settlement）。

### P2（仲裁与自动验证增强）

1. 自动规则仲裁（超时、哈希不匹配、格式错误）。
2. 去中心化仲裁池接口与裁决执行器。
3. 多 Agent 责任路径哈希检测（循环授权、互刷识别）。
4. 子身份增强与隐私增强（展示 ID 轮换）。

### P3（高级能力）

1. 外部仲裁生态接入（ETH arbitration ecosystem）。
2. ZK 额度证明、选择性披露增强。
3. 企业身份与法律身份绑定工作流。
4. 批量净额结算。

---

## 7. 数据模型（建议新增/扩展）

### 7.1 身份与额度

- `identity`（主身份）
- `sub_identity`（最多 2 个，强约束）
- `capacity_ledger`
  - `total_locked_usdc`
  - `available_credits`
  - `reserved_credits`
  - `in_progress_credits`
  - `confirmed_progress_credits`
  - `disputed_credits`
  - `pending_settlement_credits`
  - `burned_credits`

### 7.2 Voucher

- `voucher_id`, `buyer_identity_id`, `seller_identity_id`, `amount`
- `task_description_hash`, `progress_rule_hash`, `evidence_requirement_hash`
- `expiry_time`, `nonce`, `signature`, `status`

### 7.3 Receipt（Execution + Progress）

- Execution Receipt：任务执行证据（输入/输出/工具调用/日志哈希）。
- Progress Receipt：阶段进度与责任确认证据（pending/confirmed）。

### 7.4 争议与裁决

- `dispute_case`
- `arbitration_material_package`
- `arbitration_decision`

---

## 8. 状态机与守卫规则（工程必须实现）

1. 所有状态迁移由统一状态机驱动。
2. 非法迁移一律拒绝并记录审计日志。
3. 关键迁移（授权冻结、结算销毁、争议冻结）必须幂等。
4. 回执验证状态（`valid/invalid/pending`）必须参与迁移条件判断。
5. 任何“已结算”状态都必须可追溯到：
   - 有效任务
   - 有效授权
   - 有效回执/确认
   - 对应资金移动与同额销毁

---

## 9. 测试与审计清单（开工即配置）

### 9.1 合约测试

1. 1:1 锚定不变量测试。
2. voucher 重放攻击测试。
3. 余额不足不可进入授权/冻结测试。
4. 结算与销毁原子性测试。
5. 暂停/熔断路径测试。

### 9.2 后端测试

1. 状态机迁移表覆盖测试。
2. 幂等重试测试（网络重试、重复回调）。
3. 账本对账巡检测试。
4. 争议冻结/裁决释放流程测试。

### 9.3 E2E 测试

1. Buyer -> Seller 最小闭环（授权、执行、结算、销毁）。
2. Buyer Regret（部分责任结算）。
3. Dispute -> Arbitration -> Partial Settlement。

---

## 10. 团队开工建议（按角色拆分）

### 合约组

- 先做 P0 的身份、授权、冻结、结算销毁闭环，不扩大战线。

### 后端组

- 先做统一状态机与 Capacity Ledger，再接自动验证。

### SDK 组

- 先稳定 Buyer/Seller 核心方法签名，避免早期频繁破坏性改动。

### 前端组

- 先做“额度与责任状态可视化”，避免金融化措辞（不出现充值/理财/收益）。

---

## 11. 版本化发布建议

1. `v1.0.0-p0`: 最小责任闭环（可上测试网）。
2. `v1.1.x`: 回执标准化 + progress/regret。
3. `v1.2.x`: 自动仲裁 + 去中心化仲裁池接入。
4. `v1.3.x`: 隐私增强与企业能力。

---

## 12. 一句话工程定义（供团队统一口径）

Karma 是一个以 USDC 全额锁仓为资金锚、以 1:1 内部责任账本为状态信号、以可验证回执和可仲裁证据驱动清算的 Agent 责任结算网络；系统核心不是支付效率，而是责任可验证与结算可执行。

