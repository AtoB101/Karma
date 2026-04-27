# TrustChain v0.1 审计附录（Non-Custodial）

本文档用于第三方审计快速对齐本轮关键改动，聚焦两项优化：

- 优化 1：参数化错误（可观测性与可诊断性增强）
- 优化 2：链下签名确认（EIP-712 `confirmBillBySignature`）

---

## 1) 参数化错误（旧代码 -> 新代码）

### 1.1 错误定义替换

旧代码（示意）：

```solidity
revert InvalidState();
```

新代码（示意）：

```solidity
revert BillNotFound(billId);
revert InvalidBillStatus(billId, expected, actual);
revert InvalidBatchStatus(batchId, expected, actual);
```

新增错误定义（`NonCustodialAgentPayment`）：

- `BillNotFound(uint256 billId)`
- `InvalidBillStatus(uint256 billId, BillStatus expected, BillStatus actual)`
- `InvalidBatchStatus(uint256 batchId, BatchStatus expected, BatchStatus actual)`

### 1.2 主要调用点替换

#### Bill 相关

- `confirmBill`
- `cancelBill`
- `disputeBill`
- `resolveDisputeBuyer`
- `resolveDisputeSeller`
- `resolveDisputeSplit`

#### Batch 相关

- `closeBatch`
- `settleBatch`

### 1.3 设计收益

- 失败原因可直接结构化解析（前端、索引器、告警系统）
- 降低“同一个 InvalidState 覆盖多种失败语义”的审计噪音
- 提升回归测试精确度（可断言 expected/actual 状态）

---

## 2) 链下签名确认（EIP-712）旧代码 -> 新代码

### 2.1 接口能力变化

旧代码：

```solidity
function confirmBill(uint256 billId) external;
```

新代码：

```solidity
function confirmBill(uint256 billId) external;
function confirmBillBySignature(uint256 billId, uint256 deadline, uint8 v, bytes32 r, bytes32 s) external;
function confirmNonce(address buyer) external view returns (uint256);
```

### 2.2 合约基础设施新增

- EIP-712 Domain Separator（name=`NonCustodialAgentPayment`, version=`1`, chainId, verifyingContract）
- 类型哈希：
  - `EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)`
  - `ConfirmBill(uint256 billId,uint256 nonce,uint256 deadline,address relayer)`
- Nonce 映射：
  - `mapping(address => uint256) public confirmNonce;`
- 签名约束：
  - high-s 拒绝
  - v 只允许 27/28
  - deadline 过期拒绝

### 2.3 核心函数逻辑（`confirmBillBySignature`）

执行顺序：

1. `deadline` 检查（过期即拒绝）
2. `s`/`v` 合法性检查
3. bill 存在校验 + pending 状态校验
4. 使用 `billId + nonce + deadline + relayer(msg.sender)` 组装 EIP-712 digest
5. `ecrecover` 校验 signer 必须是 bill 的 buyer
6. nonce 自增，bill 状态置 `Confirmed`
7. 发出 `BillConfirmed`

---

## 3) 测试映射（新增与更新）

### 3.1 新增测试

- `testConfirmBillBySignatureSuccess`
- `testConfirmBillBySignatureRevertsOnReplay`
- `testConfirmBillBySignatureRevertsOnBadSignature`

### 3.2 既有测试更新

- 参数化错误断言更新（`abi.encodeWithSelector(...)`）
- batch 状态错误断言从无参错误升级为 expected/actual 断言

### 3.3 回归命令

```bash
forge test -vv
```

本轮结果：全量通过（0 failed）。

---

## 4) 关联优化（同轮落地）

> 以下项虽不属于本附录核心主题，但与本次提交同时落地：

- `settleBatch` 单次处理上限：`MAX_BATCH_SETTLE_SIZE = 200`
- 批次游标推进：`batchNextSettleIndex`
- 批次剩余计数：`batchRemainingCount`

目的：避免 O(n) finalize 扫描和分页重复扫前 N 条导致的大批量处理退化。

---

## 5) 明确不改边界

本轮未改动：

- 非托管资金模型（仍为用户钱包余额 + 授权 + 链上逻辑锁）
- 仲裁角色模型（`arbitrator` 架构不变）
- `proofHash` 类型（仍为 `string`，未切换 `bytes`）
- 部署脚本/运维脚本参数语义（本轮以合约、接口、测试为主）

---

## 6) 审计关注建议

建议外部审计重点复核：

1. `confirmBillBySignature` 的 domain 绑定与 relayer 绑定是否符合业务预期
2. nonce 递增与多 relayer 并发场景下的重放行为
3. 参数化错误是否与前端错误分级系统一致
4. 大批次下 `settleBatch` 游标推进的终止条件与可达性
5. 裁决与批次 finalize 交互对不变式的影响

