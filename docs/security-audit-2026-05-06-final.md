# 🔐 Karma 反向逻辑安全审计 — 攻击者视角

> 方法: 逐函数推演攻击路径，验证每条状态转换  
> 目标: 公开 `main` @ `3dde5b5`（5 合约）+ 私有 `main` @ `37e2133`（8 合约）

---

# 一、NonCustodialAgentPayment（920 行）

## 资产流模型

```
lockFunds → [active] ──→ createBill → [reserved] ──→ confirmBill
                                                        ├── requestBillPayout → 转账 seller
                                                        ├── disputeBill → [disputed] → arbitrator 裁决
                                                        ├── cancelBill → 退回双方
                                                        └── expireBill → 退回双方
```

## 攻击路径逐一推演

### A1: 双花攻击 — settleBatch 重入

**攻击链：**
1. 部署恶意 ERC20，`transferFrom` 回调 `settleBatch`
2. batch 有 200+ Confirmed bill，调用 `settleBatch(batchId, 200)`
3. `_settleConfirmedBill(bill[0])` → `_safeTransferFrom` → 恶意 token 回调 → 再次 `settleBatch`

**内层调用：**
```
start=0, end=200
bill[0]: 状态=Settled（外层已标记）→ 跳过
bill[1]~[199]: 处理结算 → _settleConfirmedBill
cursor → 200
```

**外层恢复：**
```
继续 i=1:
bill[1]~[199]: 全部 Settled → 跳过
cursor → 200
```

**结论: 🔵 不可利用。** CEI 保护使每笔 bill 先标记 Settled 后转账。内层和外层在 cursor=200 收敛。无重复支付、无 bill 跳过、无资金损失。仅浪费 gas。

### A2: 签名伪造 — confirmBillBySignature

**攻击链：** 从 mempool 捕获 `(billId, deadline, v, r, s)`
- SignatureValidator.recoverStrict 拒绝 s>n/2 ✅
- SignatureValidator.recoverStrict 拒绝 v∉{27,28} ✅
- SignatureValidator.recoverStrict 拒绝 r=0 或 s=0 ✅
- EIP-712 结构包含 relayer 绑定 → 签名不可跨 relayer 重放
- nonce 递增 → 同一 buyer 不可重放

**结论: ✅ 不可利用。**

### A3: 卖家 dispute DoS

**攻击链：** 卖家对每笔 Confirmed bill 调用 `disputeBill`
- `SELLER_DISPUTE_COOLDOWN_SECONDS = 5分钟` → 每 5 分钟最多 1 次 per seller
- 买家无冷却限制（设计意图：买家是付款方，应有权快速争议）

**结论: 🟡 低影响。** 卖家可每 5 分钟争议 1 笔确认订单，但需消耗 gas。若有 100 笔确认订单，需 500 分钟 = 8.3 小时才能全部争议。买家不受此限制。

### A4: settleBatch 游标混乱

**结论: 🔵 不可利用。** 见 A1 分析，内外层调用在相同终点收敛。

### A5: 空 batch closeBatch 崩溃

**触发：** `createBill` 在 `_ensureOpenBatch` 后、`batchBillIds.push` 前 revert → batch 为 Open 但有 0 笔 bill  
**closeBatch 中：** `bills[batchBillIds[batchId][0]]` → 数组越界 revert

**结论: 🔵 孤儿 batch。** 无资金损失，仅永久占用 1 个 batchId。

### A6: 策略引擎绕过

- `_enforcePolicy` 对 policyByOwner[owner] 无配置时直接跳过 ✅
- createBill 强制 `finalDeadline ≤ policy.validUntil` ✅
- 日限额 / 每笔限额 / 小时频率 三维限制 ✅
- 对手方 + Scope 白名单 ✅
- 策略可被 owner 随时修改 → 可先创建 bill 再改策略

**结论: 🟡 Owner 自主风险。** 策略由 owner 自行配置，不存在第三方绕过。

### A7: 裸 call 转账 — `_safeTransferFrom`

```
token.call(abi.encodeWithSelector(TRANSFER_FROM_SELECTOR, from, to, amount))
```

- 对无返回值 token：`data.length==0 → return true` ✅
- 对 revert token：`success=false` → propagate revert ✅
- 对 ERC777 回调 token：外层 `nonReentrant` 保护争议/结算/ payout 函数 ✅
- 唯一未保护路径：settleBatch（公开版本）

**结论: 🟡 Low。** 所有调用点（除 settleBatch）有 nonReentrant。settleBatch 不可利用（见 A1）。建议改用 SafeERC20 获得编译时保护。

---

# 二、SettlementEngine（116 行）

### B1: 签名伪造 — submitSettlement

**攻击链：** 伪造 EIP-712 Quote 签名
- SignatureValidator.recoverStrict → 拒绝锻造签名 ✅
- executedQuotes[quoteId] → 拒绝重放 ✅
- nonces[payer] → 拒绝乱序 ✅
- tokenAllowed → 拒绝未授权 token ✅
- deadline < block.timestamp → 拒绝过期 ✅

**结论: ✅ 不可利用。**

### B2: settleBatch 重入

```
function settleBatch(quotes, vs, rs, ss) external nonReentrant
```

- nonReentrant 修饰符 ✅
- 内部 `_submitSettlement` 逐条处理，每条独立 nonce+quoteId ✅

**结论: ✅ 不可利用。**

### B3: 抢跑 griefing

**攻击：** 监控 mempool，看到合法 quote → 用自己的交易抢跑 `submitSettlement(quote, v, r, s)`
- 攻击者交易成功 → executedQuotes[quoteId]=true，nonces 递增
- 受害者交易失败 → QuoteAlreadyExecuted
- 攻击者支付了 gas，受害者损失了该 quote

**结论: 🔵 Griefing，无资金损失。** 受害者可重新签名新 quote（不同 nonce）。

---

# 三、AuthTokenManager（119 行）

### C1: consumeAuth 重放

**攻击：** 捕获 `(tokenId, agent, opType, amount, deadline, v, r, s)`
- usedDigests[digest] → 每个 digest 只能用一次 ✅
- token.used = true → token 只能用一次 ✅
- deadline < block.timestamp → 拒绝 ✅
- SignatureValidator.recoverStrict → 拒绝锻造 ✅

**结论: ✅ 不可利用。** 双因子防重放：digest 级别 + token 级别。

### C2: tokenId 碰撞伪造

**攻击：** 构造碰撞 tokenId = keccak256(owner, agent, opType, maxAmount, nonce, validUntil, chainId)
- keccak256 抗碰撞 ✅
- 即使碰撞，consumeAuth 仍需 valid EIP-712 签名 by token.owner ✅
- token.owner 在 issueAuthToken 时设为 msg.sender ✅

**结论: ✅ 不可利用。**

---

# 四、KYARegistry（81 行）

### D1: DID 劫持

**攻击：** 注册已被 Alice 占用的 agent 地址
```
if (existing.isActive && existing.validUntil >= block.timestamp) {
    if (existing.owner != msg.sender) revert Unauthorized();  ← 拦截
```
**结论: ✅ 不可利用。**

### D2: stake 提取

只有 `admin` 可调用 `withdrawStuckETH`。  
**结论: ✅ admin 单点信任，无外部攻击面。**

---

# 五、CircuitBreaker（62 行）

### E1: humanApprovalThreshold 影响面

公开 main 上：
- NCAP 使用 `_enforcePolicy`（不读 threshold）
- SettlementEngine 不读 threshold
- 无 BillManager → 无读者

**结论: 🔵 无实际影响。** 缺失 MAX_THRESHOLD 不产生安全风险。

---

# 六、私有仓库独有：BillManager + LockPoolManager

### F1: BillManager 重入（Karma2 已修）

10 分钟前推送的 `16e78de` 已全部添加 nonReentrant。  
**结论: ✅ 已修复。**

### F2: setBillManager 时间锁（Karma2 已修）

`BILL_MANAGER_CHANGE_DELAY = 1 days` 两步替换。  
**结论: ✅ 已修复。**

### F3: LockPoolManager fund drain via malicious BillManager

**攻击链（已修复前）：** admin 私钥泄露 → `setBillManager(malicious)` → 恶意合约 drain pool
**现在：** 1 天延迟 + 事件通知 → 给监控系统反应时间  
**结论: ✅ 缓解。** 仍有 admin 单点信任，但攻击窗口从即时变为 1 天。

---

# 七、总评

## 攻击面总结

| 合约 | 攻击路径 | 结果 |
|------|---------|------|
| NCAP | settleBatch 重入 | 🔵 不可利用（CEI 保护） |
| NCAP | 签名伪造 | ✅ 不可利用（recoverStrict） |
| NCAP | 卖家 dispute DoS | 🟡 5分钟冷却，可接受 |
| NCAP | 空 batch 崩溃 | 🔵 孤儿 batch，无损失 |
| NCAP | 裸 call 转账 | 🟡 有 nonReentrant 保护 |
| SettlementEngine | 签名伪造/重放 | ✅ 不可利用 |
| AuthTokenManager | 重放/碰撞 | ✅ 不可利用 |
| KYARegistry | DID 劫持 | ✅ 不可利用 |
| CircuitBreaker | 阈值绕过 | 🔵 无读者 → 无影响 |
| BillManager (K2) | 重入 | ✅ 已修复 |
| LockPoolManager (K2) | 时间锁 | ✅ 已修复 |

## 评级

| 仓库 | 可攻击路径 | 最高严重度 | 评分 |
|------|-----------|-----------|------|
| 公开 main | 0（无资金损失路径） | 🟡 Low | **9.2/10** |
| 私有 main | 0（无资金损失路径） | 🔵 Info | **9.5/10** |

---

*Security Sentinel · 反向逻辑审计 · 2026-05-06 06:10 GMT+7*
