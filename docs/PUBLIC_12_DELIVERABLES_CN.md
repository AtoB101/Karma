# Karma 公开仓库 12 项落地清单（执行版）

本清单用于锁定公开仓库范围，仅交付以下 12 项。

## 清单与落位

| # | 目标项 | 公开仓库落位 | 当前状态 |
|---|---|---|---|
| 1 | KarmaIdentitySBT 合约 | 概念映射到 `karma-core/contracts/core/KYARegistry.sol`（身份/注册主路径） | 已有主路径 |
| 2 | KarmaVault 锁仓合约 | 概念映射到 `karma-core/contracts/core/NonCustodialAgentPayment.sol`（`lockFunds/unlockFunds`） | 已有主路径 |
| 3 | KarmaBillLedger 账单额度合约 | 概念映射到 `NonCustodialAgentPayment.sol` 账户状态与不变量；公开 API `capacity` 账本补齐 | 已落地 |
| 4 | KarmaVoucher 授权凭证合约 | 授权主路径：`AuthTokenManager.sol`；公开 API `v1/vouchers/*` 已落地 | 已落地 |
| 5 | KarmaTaskManager 任务状态机 | `core/schemas.py` + `core/settlement/engine.py` + `api/routes/settlement.py` | 已落地（含 P2 dispute/auto-arbitrate） |
| 6 | KarmaSettlementEngine 结算与账单币销毁 | 概念映射到 `SettlementEngine.sol` + `NonCustodialAgentPayment.sol` 结算路径，公开侧补齐 dispute/auto-arbitrate/仲裁池执行接口 | 已落地（P2骨架） |
| 7 | 基础 SDK | `sdk/client.py`, `sdk/task.py`, `sdk/adapters.py` | 已落地 |
| 8 | 接入文档 | `README.md`, `docs/API_REFERENCE.md`, `docs/AGENT_INTEGRATION.md` | 已落地 |
| 9 | Execution Receipt 标准格式 | `docs/EXECUTION_RECEIPT_STANDARD.md` + `packages/evidence-schema/execution-receipt.schema.json` | 本次补齐 |
| 10 | API / MCP / Agent Runtime 基础适配器 | `sdk/adapters.py`（含 P2 AI Workflow 模板） | 已落地 |
| 11 | 测试用例 | `tests/integration/test_api.py`, `tests/unit/test_sdk_adapters.py`, 合约测试 `karma-core/contracts/test/*.t.sol` | 已落地 |
| 12 | 审计报告 | `audits/2026-05-12_security-audit.md` | 已落地 |

## 执行边界

1. 不在公开仓暴露私有评分/反作弊阈值。
2. 不新增并行结算权威合约栈；概念名统一映射到现有 canonical contracts。
3. 所有新增能力必须有公开文档与最小测试覆盖。

