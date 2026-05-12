# Karma 公开仓库 — P0 / P1 审计修复清单（与 NC 主线对照）

本文档把团队给出的 **BillManager / LockPoolManager / DemoToken** 类 P0 条目，与当前 **公开仓库** (`AtoB101/Karma`) 实际代码路径对齐。

## 当前公开核心（`contracts/core`）

主线为 **NonCustodial + SettlementEngine**，仅包含：

| 文件 |
|------|
| `NonCustodialAgentPayment.sol` |
| `SettlementEngine.sol` |
| `AuthTokenManager.sol` |
| `KYARegistry.sol` |
| `CircuitBreaker.sol` |

下列路径在**本仓库中不存在**（多在私有仓 **Karma2** 或其它含 BM 栈的分支）：

- `contracts/core/DemoToken.sol`
- `contracts/core/BillManager.sol`
- `contracts/core/LockPoolManager.sol`

因此标为 **P0(BM)** / **P1(BM)** 的项必须在 **含上述合约的仓库或分支**上执行与验收；参见 `docs/SECURITY_UPGRADE_PLAN.md` §0 映射。

---

## P0 七项 — 状态

| # | 条目 | 公开仓状态 |
|---|------|------------|
| 1 | `DemoToken.sol` — `mint()` `onlyOwner` 或删除合同 | **不适用**：本仓无 `DemoToken.sol`。若测试网需 demo 币，在专用分支或 Karma2 增加并限 owner。 |
| 2 | `AuthTokenManager.sol` — 裸 `ecrecover` → `SignatureValidator.recoverStrict` | **已满足**：`consumeAuth` 使用 `SignatureValidator.recoverStrict`。 |
| 3 | `BillManager.sol` — 全部公开函数 `nonReentrant` | **不适用（本仓无 BM）**。NC 对标：`SettlementEngine` / `NonCustodialAgentPayment` 关键路径应有 `nonReentrant`（维持现有测试门禁）。 |
| 4 | `BillManager.sol` — 批次 `MAX_BATCH_SIZE=200` 等 | **不适用（本仓无 BM）**。NC：`SettlementEngine` / NC 批量路径已有批量上限时请保持与清单一致并有测试。 |
| 5 | `KYARegistry.sol` — `registerDID` 加强 `existing.owner` 检查 | **已加固**：对已存在记录（含已撤销或过期）若 `existing.owner != 0` 且调用者不是该 owner，一律 `Unauthorized`；仍在有效期内的 DID 续期逻辑不变。测试见 `KYARegistry.t.sol`。 |
| 6 | `LockPoolManager.sol` — 核心函数 `nonReentrant` | **不适用（本仓无 LM）**。在 Karma2 或 BM 栈仓库执行。 |
| 7 | `BillManager.sol` — `_settleBatch` 检查账单 deadline | **不适用（本仓无 BM）**。NC：`NonCustodialAgentPayment` 等对 deadline 的检查保持与审计要求一致。 |

---

## P1（48h）— 状态

| # | 条目 | 说明 |
|---|------|------|
| 1 | 合并 `cursor/audit-high-fixes-dfef` | **勿直接全量合并进当前公开主线**：该分支历史可能仍含已移除的 `karma-engine/` 路径，会与「公开仓已剔除引擎」冲突。请将 **单笔提交** cherry-pick 到当前分支，或仅在 Karma2/BM 栈分支合并。 |
| 2–3 | 从 Karma2 手工移植 LockPoolManager / BillManager 分页 | **在 Karma2 或含 BM 的仓库执行**；公开仓不保留 BM 源代码时，此处仅追踪跨仓清单与门禁。 |
| 4 | KYARegistry：管理员 + `withdrawStuckETH` | **已具备**：构造时 `admin = msg.sender`；`withdrawStuckETH` 仅 `admin` 可调用。 |

---

## 验收命令（公开仓）

```bash
forge build
forge test -vv
```

---

## 变更记录（公开仓已执行）

- `KYARegistry.registerDID`：绑定 `agent` 槽位到首登 `owner`，防止第三方在 owner 撤销后抢注。
