# 最小安全灰度 — 验收矩阵（对照「第八节」15 条）

将「真实资金小规模灰度」前置条件映射到本仓库的**实现入口**、**自动化测试**与**已知缺口**，供上线前逐项核对。不替代威胁建模或第三方审计。

## 使用说明

- **实现入口**：从该路径继续阅读代码或 OpenAPI。
- **测试**：仓库根目录执行 `python3 -m pytest <路径> -q`。
- **进程内安全态**：`tests/conftest.py` 在每测前后重置全局 Runtime Safety，避免用例间泄漏暂停开关。
- **缺口**：可能为配置、链上部署、私有风控或文档态与代码枚举未完全对齐。

## 第八节 — 15 条最小标准

| # | 标准要求 | 主要实现入口 | 示例测试 | 缺口 / 备注 |
|---|----------|--------------|----------|-------------|
| 1 | USDC 1:1 锁仓与账单额度 | `api/routes/capacity.py`, `services/capacity_ledger.py` | `test_p0_acceptance.py::test_p0_global_capacity_anchor_not_breached` | 链上 Vault 与账本对账需部署环境验收 |
| 2 | Runtime Key 生成 / 验证 / 吊销 | `api/routes/runtime_gateway.py`, `services/runtime_key_service.py`, `db/models/orm.py` | `test_runtime_gateway.py`, `test_runtime_e2e.py` | 设备绑定等属 P1 |
| 3 | Runtime Key 权限隔离 | Runtime Gateway、`packages/karma-runtime-sdk` | `test_runtime_e2e.py` | 持续审计权限表 |
| 4 | Voucher 与额度冻结 | `api/routes/vouchers.py` | `test_p0_acceptance.py::test_p0_voucher_accept_moves_capacity` | 生产 EIP-712 开关 |
| 5 | 任务状态机 | `core/settlement/engine.py`, `api/routes/settlement.py` | `test_api.py::test_settlement_invalid_transition_rejected` | 文档 17 态映射见 `core/schemas.py` |
| 6 | Execution Receipt 防伪 | `api/routes/receipts.py`, `services/receipt_guard.py`, `settlement_receipt_release_guard.py` | `test_p0_buyer_accept_requires_success_receipt`, `test_level2_attack_mitigations.py` | 私有风控为部署项 |
| 7 | Progress 与反悔 | `api/routes/progress.py`, `settlement.py`（regret / partial） | `test_progress_receipt_and_buyer_regret_flow`, `test_p1_progress_partial_guards.py` | 超时确认依赖配置 |
| 8 | 未结清不释放锁仓 | `capacity.py` 的 `release` 仅扣减 `available_credits` | `test_p0_security_mode_dispute_e2e.py` | 更严业务规则可再加 |
| 9 | Settlement 与额度销毁 | `services/capacity_resolution.py` | `test_p0_settlement_records_burn_on_buyer_accept` | 链上对账 |
|10 | Dispute 冻结 | `settlement.py`, `move_reserved_to_disputed` | `test_p0_dispute_moves_reserved_to_disputed` | — |
|11 | 总账校验 | `runtime_safety.py::audit_capacity_anchor_and_maybe_trip` | `test_runtime_safety.py::test_anchor_audit_trips_runtime_safety_mode_on_breach` | 生产需调度 anchor-audit |
| 12 | 安全模式 | `runtime_safety.py`, `api/routes/security.py` | `test_runtime_safety.py`, `test_p0_security_mode_dispute_e2e.py` | `release_unused_capacity` 在暂停新业务时仍允许释放可用额度；pytest 见上 |
|13 | Console 同步 | `apps/console/` | 无自动化 E2E | Playwright 等可排期 |
|14 | 私有风控 | `security_policy_center.py` | `test_security_ops.py` | 规则在私有边界 |
|15 | E2E 通过 | 集成组合 | `test_p0_acceptance.py`, `test_api.py`, `test_p0_security_mode_dispute_e2e.py` | 预发全链路 |

## 第七节 — 安全测试与用例索引

| 意图 | 用例或区域 |
|------|------------|
| 非法状态跳转 | `test_settlement_invalid_transition_rejected` |
| Disputed 不得 buyer-accept | `test_p0_security_mode_dispute_e2e.py` |
| 安全模式拦新业务、争议与仲裁可推进 | `test_p0_security_mode_dispute_e2e.py` |
| 安全模式下可释放未占用额度 | `test_p0_security_mode_dispute_e2e.py`（`release_unused_capacity`） |
| 重复 Voucher | `test_p0_voucher_double_accept_rejected` |
| Progress 不倒退 / 重复 | `test_progress_receipt_rejects_rollback_and_duplicate_hash_pair` |

## 维护

合并新 P0 时请同步更新本表一行。`TaskStatus` 与对外文档命名以 `core/schemas.py` 与 `core/settlement/engine.py` 为准。
