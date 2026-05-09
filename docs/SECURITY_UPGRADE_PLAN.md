# Karma Pay 主网上线安全升级方案（SECURITY_UPGRADE_PLAN）

> **版本**: v1.0 | **日期**: 2026-05-02 | **状态**: 待执行  
> **仓库**: [github.com/AtoB101/Karma](https://github.com/AtoB101/Karma)（public）/ [github.com/AtoB101/Karma2](https://github.com/AtoB101/Karma2)（private）  
> **文档性质**: 技术部执行清单 + 验收方逐项签字  
> **适用范围**: Karma Pay 主网部署前安全升级；公开核心与私有引擎双仓联动一致

---

## 与当前 Karma 仓库的映射（验收前必读）

本仓库 **`karma-core/contracts`** 当前为 **NonCustodial（NC）+ SettlementEngine** 主线，**不包含**下列旧栈路径：

| 方案中的文件/模块 | 在当前仓库中 |
|-------------------|--------------|
| `contracts/test/BillAndBatch.t.sol` | **不存在** |
| `contracts/core/BillManager.sol` | **不存在** |
| `contracts/core/LockPoolManager.sol` | **不存在** |

**含义**：

- 方案 **§2 P0-1～P0-3、P1-3（BillManager expireBill）** 适用于 **BillManager + LockPool（BM）栈** 或独立分支/子模块；若主网仍走该栈，须在**含 BM 代码的仓库/分支**上执行并验收。
- 当前 **NC 主线** 上对应关系供验收时替换检查项：
  - **批量 gas 上限**：`NonCustodialAgentPayment` 已有 `MAX_BATCH_SETTLE_SIZE`；`SettlementEngine.settleBatch` 若需与方案一致，应补 **单笔 batch 数组长度上限** + 测试。
  - **重入**：`SettlementEngine` 结算路径带 `nonReentrant`；`NonCustodialAgentPayment` 关键路径带 `nonReentrant`（与方案中 LockPoolManager 加固目标同类）。
  - **expireBill**：`NonCustodialAgentPayment.expireBill` **已实现**（Pending/Confirmed 超时释放）。
- **CI 名称**：下文示例中的 `Trust-Chain CI` / 单文件 `ci.yml` 为模板；本仓库实际为 `.github/workflows/forge-ci.yml`、`security-ci.yml` 等，以**仓库内文件为准**做门禁对齐。

---

# Karma Pay 主网上线安全升级方案（正文 v1.0）

## 1. 执行摘要

| 指标 | 现状 | 目标 |
|------|------|------|
| 合约编译 | ❌ 测试套件编译失败 | ✅ 全量通过 |
| 测试覆盖 | ⚠️ NC 模块有测试，BM 模块测试不通过 | ✅ 全模块可运行 |
| 静态分析 | ❌ 未集成 | ✅ CI 中 Slither 自动运行 |
| 多签控制 | ❌ 全部单地址 admin | ✅ Gnosis Safe 3/5 |
| 部署验证 | ❌ 无自动化 | ✅ 部署后 bytecode hash 校验 |
| 监控告警 | ⚠️ 仅 cron 轮询 | ✅ 事件驱动 + 阈值告警 |
| 应急响应 | ❌ 无预案 | ✅ 分级 SOP |

**优先级**：P0 = 阻塞上线 | P1 = 上线前必须 | P2 = 上线后第一周 | P3 = 持续迭代

---

## 2. 合约修复清单

### P0-1: 修复 BillAndBatch.t.sol 编译错误

**文件**: `contracts/test/BillAndBatch.t.sol`，约第66行  
**问题**: Solidity 不允许将 struct 中的 enum 字段直接解构为 `uint8`

**当前代码（第59-71行）**:

```solidity
(
    uint256 loadedBatchId,
    bytes32 loadedPoolId,
    uint256 totalPending,
    uint256 billCount,
    uint8 status,          // ← 编译错误在这里
    uint256 createdAt,
    uint256 settledAt
) = bill.batches(1);
assertEq(status, uint8(2), "status should be Settled");
```

**修复为**:

```solidity
Types.Batch memory batch = bill.batches(1);
assertEq(batch.batchId, 1, "batch id");
assertEq(batch.poolId, poolId, "pool id");
assertEq(batch.totalPending, 100, "pending snapshot");
assertEq(batch.billCount, 1, "bill count");
assertEq(uint8(batch.status), uint8(Types.BatchStatus.Settled), "status should be Settled");
assertGt(batch.createdAt, 0, "createdAt");
assertGt(batch.settledAt, 0, "settledAt");
```

**验证**: `forge test --match-contract BillAndBatch -vvv`

---

### P0-2: BillManager.settleBatch 加 Gas 上限

**文件**: `contracts/core/BillManager.sol`  
**问题**: 无限循环遍历所有 bill，大 Batch 下 gas 耗尽导致资金永久锁死

**当前代码中的 for 循环**:

```solidity
for (uint256 i = 0; i < ids.length; i++) {  // ← 无上限
```

**修复方案**（参考 NonCustodialAgentPayment 的游标分页模式）

合约顶部新增:

```solidity
uint256 public constant MAX_BATCH_SETTLE_SIZE = 200;
mapping(uint256 batchId => uint256) public batchNextSettleIndex;
mapping(uint256 batchId => uint256) public batchRemainingCount;
```

`settleBatch` 改为:

```solidity
function settleBatch(uint256 batchId) external override {
    Types.Batch storage batch = batches[batchId];
    if (batch.batchId == 0) revert Errors.NotFound();
    if (batch.status != Types.BatchStatus.Closed) revert Errors.InvalidState();
    _checkBatchOwnerAuthorization(batchId);
    uint256[] storage ids = batchBills[batchId];
    uint256 remaining = ids.length - batchNextSettleIndex[batchId];
    uint256 limit = remaining < MAX_BATCH_SETTLE_SIZE ? remaining : MAX_BATCH_SETTLE_SIZE;
    uint256 end = batchNextSettleIndex[batchId] + limit;
    uint256 totalSettled;
    for (uint256 i = batchNextSettleIndex[batchId]; i < end; i++) {
        Types.Bill storage bill = bills[ids[i]];
        if (bill.status == Types.BillStatus.Confirmed) {
            lockPoolManager.settleFromPendingAndPayout(
                billPoolId[bill.billId], bill.toAgent, bill.amount
            );
            bill.status = Types.BillStatus.Settled;
            totalSettled += bill.amount;
        }
    }
    batchNextSettleIndex[batchId] = end;
    if (end == ids.length) {
        batch.status = Types.BatchStatus.Settled;
        batch.settledAt = block.timestamp;
        emit Events.BatchSettled(batchId, batch.poolId, totalSettled);
    }
}
```

---

### P0-3: LockPoolManager 加重入保护

**文件**: `contracts/core/LockPoolManager.sol`  
**问题**: `settleFromPendingAndPayout` 和 `withdrawLockPool` 执行外部 transfer 无重入防护

合约顶部加:

```solidity
uint256 private constant _NOT_ENTERED = 1;
uint256 private constant _ENTERED = 2;
uint256 private _status = _NOT_ENTERED;
modifier nonReentrant() {
    if (_status == _ENTERED) revert Errors.ReentrancyGuard();
    _status = _ENTERED;
    _;
    _status = _NOT_ENTERED;
}
```

`settleFromPendingAndPayout` 和 `withdrawLockPool` 函数签名加 `nonReentrant` modifier。

`Errors.sol` 加:

```solidity
error ReentrancyGuard();
```

---

### P1-1: 全部 admin/owner 迁移到多签

`NonCustodialAgentPayment` / `SettlementEngine` / `CircuitBreaker` 的 immutable admin 不可修改。需**重新部署**时传 Gnosis Safe 多签地址而非 EOA:

```solidity
NonCustodialAgentPayment(gnosisSafeAddr, 3000, 1 days);
SettlementEngine(gnosisSafeAddr);
CircuitBreaker(gnosisSafeAddr);
```

`LockPoolManager` admin 非 immutable，可部署后迁移:

```solidity
function transferAdmin(address newAdmin) external {
    if (msg.sender != admin) revert Errors.Unauthorized();
    admin = newAdmin;
}
```

**目标架构**:

```
Gnosis Safe 3/5
  ├── Owner/Admin (合约管理)
  ├── Arbitrator   (争议裁决)
  └── CircuitBreaker (紧急暂停)
```

推荐 3/5 签名者: 莱恩、联创/CTO、安全顾问、法律/合规、冷备份硬件钱包（异地）

---

### P1-2: CircuitBreaker 阈值强制执行

`humanApprovalThreshold` 目前设置了但从任何调用路径都不检查 — **这是安全幻觉**（链上参数存在但永不生效）。

`BillManager.createBill` 开头加:

```solidity
uint256 threshold = circuitBreaker.humanApprovalThreshold(msg.sender);
if (threshold > 0 && amount > threshold) {
    revert Errors.ExceedsHumanApprovalThreshold(amount, threshold);
}
```

或者在链下 relay 层打包交易前检查阈值。

---

### P1-3: BillManager 加 expireBill

Bill 有 deadline 但没有 expire 入口，过期 bill 会永久锁在 pendingAmount。

新增函数:

```solidity
function expireBill(uint256 billId) external override {
    Types.Bill storage bill = bills[billId];
    if (bill.billId == 0) revert Errors.NotFound();
    if (bill.status != Types.BillStatus.Pending 
        && bill.status != Types.BillStatus.Confirmed) {
        revert Errors.InvalidState();
    }
    if (block.timestamp <= bill.deadline) revert Errors.NotExpired();
    lockPoolManager.releasePendingOnCancel(billPoolId[billId], bill.amount);
    bill.status = Types.BillStatus.Cancelled;
    emit Events.BillCancelled(billId, msg.sender);
}
```

需配套测试: `testExpirePendingBill`、`testExpireConfirmedBill`

---

### P2-1: Solidity 版本升级

`foundry.toml`: `solc_version = "0.8.28"`（若当前为 0.8.24，升级需全量回归）

### P2-2: optimizer_runs 调整

`foundry.toml`: `optimizer_runs = 1000`（若当前为 200，变更需 gas 快照对比）

### P2-3: safeTransferFrom 常量选择器

`NonCustodialAgentPayment.sol` 中，将 `bytes4(keccak256("transferFrom(address,address,uint256)"))` 替换为常量:

```solidity
bytes4 private constant TRANSFER_FROM_SELECTOR = 0x23b872dd;
```

每次调用时不再重新计算 `keccak256`，省 gas。

---

## 3. 工程基础设施

### CI/CD 流水线

本仓库**当前**使用多 workflow（以仓库内文件为准），与单文件 `ci.yml` **等价整合**即可：

- `/.github/workflows/forge-ci.yml` — 构建与测试
- `/.github/workflows/security-ci.yml` — Foundry + Slither + release-readiness
- `/.github/workflows/security-baseline-guard.yml`、`visibility-guard.yml` — 安全基线与可见性

**单文件合并示例（Karma Pay CI）** — 若合并为一条流水线，请将 `target` / `forge test -C` 指向 **`karma-core/contracts`**（本仓库合约根路径）：

```yaml
name: Karma Pay CI
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive
      - name: Install Foundry
        uses: foundry-rs/foundry-toolchain@v1
      - name: Run tests
        run: forge test -C karma-core/contracts -vvv --gas-report
      - name: Run invariant tests
        run: forge test -C karma-core/contracts --match-contract Invariant -vvv
      - name: Check coverage
        run: forge coverage -C karma-core/contracts --report lcov
      - name: Static Analysis
        uses: crytic/slither-action@v0.4.0
        with:
          target: karma-core/contracts/
```

### 静态分析（门禁目标由验收签字）

```bash
pip install slither-analyzer aderyn
# 目标：主网前与验收方约定为「零 high」或书面接受项（见 docs/SECURITY_ACCEPTANCE_NOTES.md）
slither karma-core/contracts --fail-high
aderyn karma-core/contracts
```

可选: 将 `aderyn` 纳入 Karma2 私有 CI 定期任务，与公开仓 Slither 策略互补。

---

## 4. 部署安全流程

### 部署前验证脚本

```bash
forge build --force || exit 1
forge test -C karma-core/contracts -vvv || exit 1
forge test -C karma-core/contracts --match-contract Invariant -vvv || exit 1
forge snapshot --diff
# 与仓库门禁对齐（或直接用 scripts/slither-gate.sh）
slither karma-core/contracts --fail-high || exit 1

# 部署后必须验证
BYTECODE_HASH=$(cast code --rpc-url $RPC_URL $CONTRACT_ADDRESS | cast keccak)
cast call $CONTRACT_ADDRESS "owner()(address)" --rpc-url $RPC_URL
cast call $CONTRACT_ADDRESS "DOMAIN_SEPARATOR()(bytes32)" --rpc-url $RPC_URL
```

### 部署脚本要求

- 使用 `vm.envUint` / 环境变量读私钥与 RPC，**禁止硬编码**
- 所有 `admin` / `owner` / `arbitrator` 参数传 **Gnosis Safe 多签地址**
- 部署后自动输出 **bytecode hash**（与链上 `cast code` 结果对照）供归档

---

## 5. 运维监控

### 关键事件告警阈值

| 事件 | 告警阈值 | 响应 |
|------|---------|------|
| GlobalCircuitBreakerTriggered | 即时 | 🔴 紧急 |
| BatchCircuitBreakerUpdated (paused=true) | 即时 | 🔴 紧急 |
| BillDisputed (seller 发起) | >5/小时 | 🟡 检查 |
| BillSplitResolved | >3/天 | 🟡 检查 |
| InvalidTransferIntent | >10/小时 | 🟡 检查攻击 |

### 余额与一致性（在现有 fund-flow-monitor 基础上加）

- 合约 ETH 余额（防止意外转入）
- 各 LockPool totalLocked vs mappingBalance 一致性（BM 栈）；NC 栈则对齐 **locked / reserved / active** 不变式监控
- deployer 地址 nonce 活动（检测私钥泄露）
- 异常大额 bill（超过历史均值 3σ）

---

## 6. 应急响应预案

| 级别 | 定义 | 响应时间 | 动作 |
|------|------|---------|------|
| 🟢 L3 | 异常无资金风险 | 24h | 记录评估 |
| 🟡 L2 | 可疑小额风险 | 4h | 分析 + 暂停相关功能 |
| 🟠 L1 | 确认攻击中等损失 | 30min | 触发 CB + 通知社区 |
| 🔴 L0 | 大规模资金损失 | 即时 | GlobalPause + 多签紧急 + 公开披露 |

### L0 响应流程

```
1. 任一多签成员调用 CircuitBreaker.emergencyPause("attack detected")
2. 所有多签成员独立验证攻击交易
3. 3/5 确认后:
   a. 联系 Etherscan 暂停验证显示
   b. Twitter/Discord 公开声明
   c. 联系 SlowMist/PeckShield 追踪资金
   d. 联系 CEX 冻结相关地址
4. 分析攻击向量 → 修补 → 重新部署 → 迁移状态
```

---

## 7. 上线前最终检查表

### 合约

- [ ] BillAndBatch.t.sol 编译通过（**仅 BM 栈仓库**；当前 karma-core 无此文件则标 N/A 并注明分支）
- [ ] BillManager.settleBatch 有 gas 上限（**BM 栈**；NC 栈验收 `MAX_BATCH_SETTLE_SIZE` + SettlementEngine 是否需上限）
- [ ] LockPoolManager 有 nonReentrant（**BM 栈**；NC 栈验收等价路径）
- [ ] 所有 admin 指向多签地址
- [ ] CircuitBreaker 阈值在调用链执行（BM：`createBill`；NC：需映射到实际策略入口）
- [ ] BillManager 有 expireBill（**BM 栈**；NC 栈验收 `NonCustodialAgentPayment.expireBill`）
- [ ] Solidity >=0.8.27（或团队批准版本）
- [ ] optimizer_runs >=1000（或团队批准值）
- [ ] safeTransferFrom 常量选择器（如适用）

### 测试

- [ ] `forge test -vvv` 全量 0 failed
- [ ] 不变式测试通过
- [ ] `forge coverage >=90%`（目标；以实际模块为准）
- [ ] Slither 策略与验收签字一致（零 high/medium 或已接受项文档化）
- [ ] Aderyn 零 warning（若启用）

### 基础设施

- [ ] CI/CD 流水线运行（forge-ci + security-ci 等）
- [ ] `foundry.toml` 无硬编码私钥
- [ ] `.env` 在 `.gitignore`
- [ ] 部署脚本无硬编码密钥

### 部署

- [ ] Sepolia 预演全部流程
- [ ] 部署后 bytecode hash 校验
- [ ] owner/arbitrator/admin = 多签
- [ ] EIP-712 domain separator 校验
- [ ] 1 ETH 小额测试交易（或等价主网代币小额）

### 运维

- [ ] 事件监控脚本部署
- [ ] 告警通道配置
- [ ] 应急 SOP 分发
- [ ] 多签成员确认
- [ ] 冷备份钱包设置

---

## 8. 修复时间线

```
Week 1: P0 修复 → CI 搭建 → Sepolia 预演
Week 2: P1 修复 → 测试覆盖 → 静态分析
Week 3: 主网部署 → 监控上线 → 小额测试
Week 4+: P2/P3 迭代 → 压力测试 → 社区披露
```

---

## 9. Karma 当前主干对照（供验收勾选替代项）

当验收 **NC 主线** 且无 BM 代码时，用下列替代原检查表中「仅 BM」条目：

| 原方案项 | NC 主线验收替代 |
|----------|----------------|
| P0-1 BillAndBatch | `forge build` + `forge test -C karma-core/contracts` 全绿 |
| P0-2 BillManager settleBatch 上限 | `NonCustodialAgentPayment` 批量上限 +（可选）`SettlementEngine` batch 长度上限 |
| P0-3 LockPoolManager 重入 | `SettlementEngine` / `NonCustodialAgentPayment` 资金路径 `nonReentrant` + 测试 |
| P1-3 BillManager expireBill | `NonCustodialAgentPayment.expireBill` + 测试 |

**技术部回传模板**（PR 或邮件）:

```
Karma Pay SECURITY_UPGRADE_PLAN v1.0 执行结果

栈: BM / NC / 双栈
P0: PR #___ 命令输出摘要 ___
P1: 多签 Safe ___ 网络 ___
P2: 排期 ___

检查表 §7: 附件链接 ___
验收负责人: ___ 日期: ___
```

---

## 10. 文档维护

- 执行状态由 **待执行** → **进行中** → **待验收** → **已关闭** 时，更新本文首行 **状态** 与日期。
- 若 BM 与 NC 分属不同分支/仓库，在 §0 表格中增加一行「实际验收仓库/分支」链接。
