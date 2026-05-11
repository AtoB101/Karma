# 🛡️ Karma 安全审计报告
**日期**: 2026-05-12 00:05 GMT+7  
**审计范围**: contracts/core/*.sol (5 合约)  
**审计人**: Sentinel (安全总监)  
**CVL 修复**: 已提交 0bb45b5

---

## 🔴 红色警报 — 0 项
无关键漏洞。Owner 不可变、无私钥泄露、无异常资金流出路径。

---

## 🟠 橙色 — 3 项 (需 30秒内 Telegram 上报)

### ORANGE-1: SettlementEngine.sol `settleBatch` 缺少重入保护
**文件**: `contracts/core/SettlementEngine.sol:47`  
**严重程度**: 🟠 中高危

```solidity
function settleBatch(...) external override {
    for (uint256 i = 0; i < length; ++i) {
        _submitSettlement(quotes[i], vs[i], rs[i], ss[i]); // 无 reentrancy 锁
    }
}
```

- `_submitSettlement` 在 `transferFrom` 之前设置了 `executedQuotes` 和 `nonces`（CEI 模式已遵循）
- **但是**: 批量循环中如果恶意 token 重入，可能绕过同批次内不同 quote 的顺序依赖
- **但是**: 无批量大小上限，可能触发 block gas limit

**修复建议**:
```solidity
function settleBatch(...) external override nonReentrant {
    require(quotes.length <= MAX_BATCH_SIZE, "batch too large");
    ...
}
```

### ORANGE-2: NonCustodialAgentPayment.sol `settleBatch` 缺少重入保护
**文件**: `contracts/core/NonCustodialAgentPayment.sol:393`  
**严重程度**: 🟠 中危

```solidity
function settleBatch(uint256 batchId, uint256 maxBills) external override returns (...) {
    // 无 nonReentrant 修饰符
    for (uint256 i = start; i < end; i++) {
        if (b.status == BillStatus.Confirmed) {
            _settleConfirmedBill(b); // 内部有 external call (transferFrom)
        }
    }
    batchNextSettleIndex[batchId] = end; // 循环结束后才更新
}
```

- `_settleConfirmedBill` 内部遵循 CEI（先改状态后转账），单次重入不会造成双重结算
- `batchNextSettleIndex` 在循环后才更新 → 重入时可能重复遍历已结算 bill（被 status 检查跳过）
- **现实风险**: 低，但违反安全最佳实践

**修复建议**: 添加 `nonReentrant` 修饰符

### ORANGE-3: CircuitBreaker.sol `emergencyResume` 无时间锁
**文件**: `contracts/core/CircuitBreaker.sol:37`  
**严重程度**: 🟠 中危

```solidity
function emergencyResume() external override onlyAdmin {
    globalPaused = false; // 即时恢复，无冷却期
}
```

- Admin 密钥泄露后，攻击者可以: 暂停 → 恢复 → 暂停，制造操作混乱
- 无最小暂停持续时间保护

**修复建议**: 添加暂停时间戳 + 最小冷却期:
```solidity
uint256 public pausedAt;
function emergencyPause(string calldata reason) external override onlyAdmin {
    globalPaused = true;
    pausedAt = block.timestamp;
}
function emergencyResume() external override onlyAdmin {
    require(block.timestamp >= pausedAt + MIN_PAUSE_DURATION, "cooldown");
    globalPaused = false;
}
```

---

## 🟡 黄色 — 5 项 (5分钟内 Telegram 上报)

### YELLOW-1: `expireBill` 无访问控制
**文件**: `NonCustodialAgentPayment.sol:296`  
任何人可调用 `expireBill()`，虽然无直接经济收益，但恶意调用可消耗 Gas。

### YELLOW-2: KYARegistry `MIN_STAKE = 0.01 ether` 硬编码
**文件**: `KYARegistry.sol:12`  
牛市时 0.01 ETH 可能过低，无法抵抗女巫攻击注册。建议添加 admin 可调参数。

### YELLOW-3: KYARegistry `withdrawStuckETH` 无事件
**文件**: `KYARegistry.sol:58`  
Admin 提款无事件记录，审计追踪不完整。

### YELLOW-4: AuthTokenManager `usedDigests` 无清理机制
**文件**: `AuthTokenManager.sol:15`  
`usedDigests` mapping 永远增长，无法清理过期条目（虽 mapping 不可遍历，但长期存储膨胀）。

### YELLOW-5: SettlementEngine `paused` 恢复无延迟
**文件**: `SettlementEngine.sol:112`  
与 ORANGE-3 类似，暂停/恢复开关无时间锁。

---

## 🔵 蓝色 — 3 项 (纳入日常报告)

### BLUE-1: Types 库与合约内结构不一致（技术债务）
- `Types.sol` 中的 `Bill` 使用 `fromAgent`/`toAgent`/`purpose`
- `NonCustodialAgentPayment.sol` 中的 `Bill` 使用 `buyer`/`seller`/`scopeHash`/`proofHash`/`sellerBond`
- 两套并行定义，表明早期重构遗留问题

### BLUE-2: EIP-712 实现未提取到共享库
- `NonCustodialAgentPayment`、`AuthTokenManager`、`SettlementEngine` 各自独立实现 DOMAIN_SEPARATOR 和签名验证逻辑

### BLUE-3: `IERC20Extended` 内联定义
- `NonCustodialAgentPayment.sol:6-9` 定义了 `IERC20Extended` 接口，应提取到 interfaces 目录

---

## ✅ 已验证的安全属性

| 属性 | 状态 | 说明 |
|------|------|------|
| Owner 不可变 | ✅ | `immutable` 在构造函数设置 |
| Arbitrator 不可变 | ✅ | `immutable` |
| 无代理/升级模式 | ✅ | 不可变合约 |
| 重入锁 | ⚠️ | 3/5 函数有保护，2个批量函数缺失 |
| CEI 模式 | ✅ | `_settleConfirmedBill` 正确实现 |
| 数值溢出 | ✅ | Solidity 0.8.24 内置保护 |
| EIP-712 签名验证 | ✅ | 非ces 重放保护、deadline 检查、签名可塑性检查 |
| 非托管模型 | ✅ | 资金不离开用户钱包 |
| 账户不变量 | ✅ | `_assertAccountInvariant` 在状态变更后调用 |

---

## 📊 风险矩阵汇总

| 等级 | 数量 | 关键项 |
|------|------|--------|
| 🔴 红色 | 0 | — |
| 🟠 橙色 | 3 | SettlementEngine+NonCustodialAgentPayment settleBatch 重入保护, CircuitBreaker 时间锁 |
| 🟡 黄色 | 5 | expireBill 访问控制, KYARegistry stake/min 提款, AuthTokenManager usedDigests, SettlementEngine pause |
| 🔵 蓝色 | 3 | 技术债务: Types 不一致, EIP-712 重复, 内联接口 |

---

## 🔧 优先修复建议

1. **立即 (本轮)**: 为 `SettlementEngine.settleBatch` 和 `NonCustodialAgentPayment.settleBatch` 添加 `nonReentrant` 修饰符
2. **本周内**: CircuitBreaker 添加暂停时间锁
3. **下版本**: 统一 Types 库与合约结构定义
4. **持续**: 提取共享 EIP-712 库

---

*Sentinel 🛡️ — 独立安全监督层, 直接向 YMZ 汇报*
