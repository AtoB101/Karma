# Karma Protocol — 最高安全级别反向审计报告

> 审计日期: 2026-04-30  
> 审计范围: `/contracts/core/*.sol` + `/contracts/libraries/*.sol`  
> 方法: 手工白盒审查 + 静态分析 + PoC 验证  
> 严重级别: Critical → High → Medium → Low → Info

---

## 审计摘要

| 级别 | 数量 |
|------|------|
| 🔴 Critical | 0 |
| 🟠 High | 4 |
| 🟡 Medium | 4 |
| 🔵 Low | 4 |
| ℹ️ Info | 2 |

---

## 🔴 Critical

**无 Critical 级别漏洞。** 对 C1（疑似重入）的 PoC 验证表明，`LockPoolManager` 的 checks-effects-interactions 模式有效阻止了资金双重支付——重入调用因 `pendingAmount` 不足必然 revert，EVM 回滚全部状态变更。

但重入向量仍然存在，降级为 High（H1）。

---

## 🟠 High

### H1 — `BillManager._settleBatch()` 重入向量（已验证 PoC）

**文件**: `contracts/core/BillManager.sol` (L207-219) + `contracts/core/LockPoolManager.sol` (L121-133)

**描述**:
`_settleBatch()` 在 `settleFromPendingAndPayout` 返回**之后**才更新 bill 状态，且 `settleBatch` / `closeAndSettleBatch` 均无 `nonReentrant` 修饰符。PoC 验证了使用带回调的 ERC20 token 时，`onTokenReceived` 可成功重入 `settleBatch`：

```
Backtrace (Foundry trace 确认):
  at BillManager.settleBatch                    ← 外层
  at MaliciousAgent.onTokenReceived              ← 回调触发
  at CallbackERC20.transfer
  at LockPoolManager.settleFromPendingAndPayout
  at BillManager.settleBatch                    ← 重入成功！
```

**当前保护**: `LockPoolManager.settleFromPendingAndPayout` 在 transfer **之前**更新 `pendingAmount`，重入时 `pendingAmount` 不足导致后续 bill 结算 revert，EVM 回滚全部重入上下文的状态变更。

**残留风险**:
1. **Gas 消耗攻击**: 重入 → revert 循环浪费调用者 gas
2. **脆弱的防护链**: 安全依赖 LockPoolManager 的状态更新顺序，而非 BillManager 自身的防护
3. **未来风险**: 若 LockPoolManager 逻辑变更（如批量转账、延迟结算），此向量可能变得可被利用
4. **跨函数重入**: `closeAndSettleBatch` 路径与 `settleBatch` 相同，且 `confirmBill` / `cancelBill` 同样在外部调用后更新状态

**修复**:
```solidity
// 方案 A: nonReentrant (最简单、最安全)
import {ReentrancyGuard} from "openzeppelin/contracts/utils/ReentrancyGuard.sol";
contract BillManager is IBillManager, ReentrancyGuard {
    function settleBatch(uint256 batchId) external override nonReentrant { ... }
    function closeAndSettleBatch(uint256 batchId) external override nonReentrant { ... }
    function confirmBill(...) external override nonReentrant { ... }
    function cancelBill(...) external override nonReentrant { ... }
    function createBill(...) external override nonReentrant { ... }
}

// 方案 B: 先标记所有 bill 再统一付款 (最彻底)
function _settleBatch(uint256 batchId, Types.Batch storage batch) internal {
    uint256[] memory ids = batchBills[batchId];
    for (uint256 i = 0; i < ids.length; i++) {
        if (bills[ids[i]].status == Types.BillStatus.Confirmed) {
            bills[ids[i]].status = Types.BillStatus.Settled; // 先标记
        }
    }
    for (uint256 i = 0; i < ids.length; i++) {
        if (bills[ids[i]].status == Types.BillStatus.Settled) {
            lockPoolManager.settleFromPendingAndPayout(...); // 后付款
        }
    }
}
```

### H2 — `KYARegistry.registerDID()` DID 劫持攻击

**文件**: `contracts/core/KYARegistry.sol` (L13-34)

**描述**: `registerDID` 允许**任何人**为**任意 agent 地址**注册/覆盖 DID，只需支付 0.01 ETH：

```solidity
function registerDID(address agent, bytes32 permissionsHash, uint256 validityDays)
    external payable override returns (bytes32 did) {
    // ⚠️ 没有检查 agent 是否已被注册
    // ⚠️ 没有检查 msg.sender 是否有权注册此 agent
    didByAgent[agent] = Types.AgentDID({
        owner: msg.sender,  // 直接覆盖 owner
        ...
    });
}
```

**攻击场景**:
1. Alice 注册 DID `didByAgent[buyer]`，owner = Alice
2. Alice 用这个 DID 创建 LockPool，存入大量资金
3. Bob 调用 `registerDID(buyer, ..., 1)`，overwrite `didByAgent[buyer].owner = Bob`
4. Bob 现在可以 `revokeDID(buyer)` 使 DID 失效
5. Alice 的后续 bill 创建全部失败（`DIDNotActive`）

虽然资金不会直接被盗，但 Bob 可以**破坏 Alice 的业务连续性**。

**影响**: 业务中断 (DoS)，stake 被覆盖丢失

**修复**:
```solidity
function registerDID(address agent, bytes32 permissionsHash, uint256 validityDays)
    external payable override returns (bytes32 did) {
    ...
    // 防止覆盖已有 DID
    Types.AgentDID storage existing = didByAgent[agent];
    if (existing.isActive && existing.validUntil >= block.timestamp) {
        revert Errors.DIDAlreadyActive();
    }
    ...
}
```

### H3 — `AuthTokenManager.consumeAuth()` ecrecover 签名可锻造性

**文件**: `contracts/core/AuthTokenManager.sol` (L91-112)

**描述**: 
1. 使用原生 `ecrecover` 而非 OpenZeppelin 的 `ECDSA`
2. **未检查 s-value 上界**（`s > secp256k1n/2`），允许签名锻造
3. **未强制 v ∈ {27, 28}**，可能接受非标准 v 值

```solidity
address recovered = ecrecover(digest, v, r, s);
if (recovered == address(0) || recovered != token.owner) revert Errors.InvalidSignature();
```

**攻击向量**: 攻击者从 mempool 观察到合法签名 `(v, r, s)`，通过 s' = n - s 构造锻造签名 `(v', r, s')`，产生**相同的 digest** → `usedDigests[digest]` 标记后，合法交易被拒绝。

**影响**: 签名抢跑/griefing，虽然不直接盗取资金但可阻断合法操作。

**修复**:
```solidity
// 1. 使用 OpenZeppelin ECDSA
import {ECDSA} from "openzeppelin/contracts/utils/cryptography/ECDSA.sol";

// 2. 或手动加 s-value 检查
require(s <= 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0, "Invalid s");
```

### H4 — `LockPoolManager.setBillManager()` 无时间锁/多签保护

**文件**: `contracts/core/LockPoolManager.sol` (L82-86)

**描述**: `setBillManager` 可被 admin 随时设置为任意地址。如果 admin 私钥泄露，攻击者可替换 BillManager 为恶意合约：

```solidity
function setBillManager(address billManager_) external override {
    if (msg.sender != admin) revert Errors.Unauthorized();
    // ⚠️ 无 timelock，无 multisig，无事件日志（interface 里没有定义）
    billManager = billManager_;
}
```

**攻击路径**: 
1. Admin 私钥泄露
2. 攻击者部署恶意合约 `MaliciousBillManager`，其 `settleFromPendingAndPayout` 直接转账给攻击者
3. `setBillManager(address(malicious))`
4. 所有 pool 资金可被 drain

**影响**: 单点故障，admin 权限过大

**修复**:
- 添加 timelock（如 48 小时延迟）
- 或使用 OpenZeppelin `Ownable2Step` 
- 或要求 multisig

---

## 🟡 Medium

### M1 — `BillManager.createBill()` 不验证 poolId 归属

**文件**: `contracts/core/BillManager.sol` (L127-140)

**描述**: `_validateAndConsumeCreateAuth` 调用 `lockPoolManager.getPoolOwner(poolId)` 但**未检查**返回值是否等于预期值。auth token 仅绑定 `(owner, agent, opType, amount)`，不绑定具体的 `poolId`。

```solidity
lockPoolManager.getPoolOwner(poolId);  // 仅读取，未校验！
```

**影响**: Auth token 可被用于 auth token owner 拥有的**任意** pool。设计意图可能是允许此行为，但如果 pool owner 拥有多个 pool，可能意外消耗到错误 pool 的资金。

**修复**: 在 auth token 中绑定 poolId，或在 createBill 中校验 pool owner。

### M2 — `BillManager._settleBatch()` 不检查 bill.deadline

**文件**: `contracts/core/BillManager.sol` (L207-219)

**描述**: Bill 在创建时设置 `deadline = block.timestamp + 1 days`，但 settle 时**完全不检查** deadline 是否已过。Bill 可以无限期挂起后被 settle。

**影响**: 过期 bill 仍可被结算，违反时间约束的业务逻辑。

**修复**:
```solidity
if (bill.status == Types.BillStatus.Confirmed) {
    if (bill.deadline < block.timestamp) revert Errors.DeadlineExpired();
    ...
}
```

### M3 — `confirmBill` / `cancelBill` 的 auth token agent 约束隐式

**文件**: `contracts/core/BillManager.sol` (L76, L89)

**描述**: `confirmBill` 和 `cancelBill` 在 `consumeAuth` 中使用 `poolOwner` 作为 `agent` 参数，这意味着 auth token 必须为 pool owner 签发（agent = poolOwner），而不是 payee。这个约束是**隐式的**，代码中没有明确文档说明。

**影响**: 集成错误 — 前端/脚本容易误以为 confirm auth token 应签发给 payee（我们在之前的 simulate 脚本调试中已经遇到这个错误）。

**修复**: 
- 在 NatSpec 中明确说明 confirmBill 的 auth token agent 必须为 pool owner
- 或添加事件/错误信息提示

### M4 — TOCTOU: DID 验证与 auth 消费之间的窗口

**文件**: `contracts/core/BillManager.sol` (L135-146)

**描述**: `_validateAndConsumeCreateAuth` 中：
```solidity
(bool fromOk,,) = kyaRegistry.verifyDID(msg.sender);  // 检查1
(bool toOk,,) = kyaRegistry.verifyDID(toAgent);        // 检查2
if (!fromOk || !toOk) revert Errors.DIDNotActive();
// ... getPoolOwner ...
authTokenManager.consumeAuth(...);                      // 消费auth
```

虽然同一 transaction 内是原子的，但如果 DID 在 mempool 中被 front-run 撤销，`consumeAuth` 时会 revert（因为 auth token 检查了 agent）。实际风险低，但代码结构不够清晰。

**修复**: 合并到 consumeAuth 的 agent 检查逻辑中（当前已经通过 `token.agent != agent` 保护）。

---

## 🔵 Low

### L1 — KYARegistry stake 永久锁定

**文件**: `contracts/core/KYARegistry.sol`

**描述**: 注册 DID 时支付的 0.01 ETH stake 永久锁定在合约中，无 withdraw 功能。即使 revoke DID 后 stake 也不能取回。

**修复**: 添加 `withdrawStake()` 函数，在 DID 过期/撤销后允许取回 stake。

### L2 — CircuitBreaker.humanApprovalThreshold 死代码

**文件**: `contracts/core/CircuitBreaker.sol` (L10, L17-20)

**描述**: `humanApprovalThreshold` mapping 可以写入（`setHumanApprovalThreshold`）但**没有任何地方读取它**。整个功能未实现。

**修复**: 实现对应逻辑，或删除死代码。

### L3 — 空 batch 可被 close/settle

**文件**: `contracts/core/BillManager.sol`

**描述**: `closeBatch` / `settleBatch` 没有检查 batch 是否包含 bill。空 batch 可以正常 close/settle，浪费 gas 且产生无意义事件。

**修复**: 添加 `batch.billCount > 0` 检查。

### L4 — `confirmBill` 在 batch closed 后仍可执行

**文件**: `contracts/core/BillManager.sol`

**描述**: `confirmBill` 只检查 `bill.status == Pending`，不检查 batch 是否已 closed。这意味着：
1. Pool owner 关闭 batch
2. Pool owner 仍可确认 batch 中的 pending bill
3. 确认后 pool owner 需要重新 settle

这是设计选择而非漏洞，但可能产生混淆。

---

## ℹ️ Info

### I1 — `BatchSettlement` 合约已废弃

**文件**: `contracts/core/BatchSettlement.sol`

**描述**: 所有函数都直接 revert `DeprecatedEntryPoint()`。建议删除此文件或添加迁移指引。

### I2 — AuthTokenManager 无 token 过期自动清理机制

**描述**: `authTokens` mapping 中的过期 token 永远不会被清理，会持续占用存储（gas 成本由用户承担）。建议添加 `cleanupExpiredToken()` 函数。

---

## 测试覆盖缺口

| 测试场景 | 状态 |
|----------|------|
| Reentrancy (C1) | ❌ 无测试 |
| DID hijacking (H1) | ❌ 无测试 |
| Signature malleability (H2) | ❌ 无测试 |
| Bill deadline enforcement | ❌ 无测试 |
| Empty batch close/settle | ❌ 无测试 |
| Multiple bills single pool settle | ⚠️ 仅在 ScenarioFlow 中 1 bill |
| Concurrent batch operations | ❌ 无测试 |
| Token with hooks reentrancy | ❌ 无测试 |

---

## 优先修复路线

```
P0 (立即):  H1 重入向量 → 添加 nonReentrant 到所有含外部调用的公开函数
P1 (本周):  H2 DID劫持 → 添加覆盖检查
P2 (本周):  H3 ecrecover → 替换为 OZ ECDSA
P3 (本月):  H4 admin权限 → 添加 timelock
P4 (本月):  M1-M5 → 边界条件加固
P5 (后续):  L1-L4 + I1-I2 → 清理改进
```

---

*Karma Protocol Security Audit · Confidential · 2026-04-30*
