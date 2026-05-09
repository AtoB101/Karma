# 🔐 Karma 双仓库修复清单

> 基于: security-audit-2026-05-06-v2.md

---

## 公开仓库 — P0 阻断（7项）

| # | 文件 | 问题 | 操作 |
|---|------|------|------|
| 1 | `contracts/core/DemoToken.sol` | mint() 无 onlyOwner | 加权限控制或删除此合约 |
| 2 | `contracts/core/AuthTokenManager.sol` | 裸 ecrecover | 移植 `SignatureValidator.recoverStrict` |
| 3 | `contracts/core/BillManager.sol` | 无 nonReentrant | 全部公开函数加 nonReentrant |
| 4 | `contracts/core/BillManager.sol` | settleBatch 无分页 | 加 MAX_BATCH_SIZE=200 + cursor |
| 5 | `contracts/core/KYARegistry.sol` | DID 可被覆盖 | 加 existing.owner 检查 |
| 6 | `contracts/core/LockPoolManager.sol` | 无 nonReentrant | 核心函数加 nonReentrant |
| 7 | `contracts/core/BillManager.sol` | deadline 不检查 | settle 时检查 block.timestamp > deadline |

## 公开仓库 — P1 48h（4项）

| # | 操作 |
|---|------|
| 8 | 合并 `cursor/audit-high-fixes-dfef` → 当前分支（推荐） |
| 9 | 或手动移植 Karma2 LockPoolManager 改进 |
| 10 | 或手动移植 Karma2 BillManager 分页 settle |
| 11 | KYARegistry 加 admin + withdrawStuckETH |

## 私有仓库 — P0 阻断（3项）

| # | 文件 | 问题 |
|---|------|------|
| K2-1 | `NonCustodialAgentPayment.sol` settleBatch | 缺 nonReentrant |
| K2-2 | `BillManager.sol` 全公开函数 | 缺 nonReentrant |
| K2-3 | `LockPoolManager.sol` setBillManager | 无 timelock |

## 私有仓库 — P1 48h（3项）

| # | 操作 |
|---|------|
| K2-4 | NCAP._safeTransferFrom → OZ SafeERC20 |
| K2-5 | 手工 ReentrancyGuard → OZ ReentrancyGuard |
| K2-6 | 双轨架构文档（NCAP vs BillManager 使用场景） |

---

**总计: 17 项修复，0 完成**
