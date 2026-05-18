# Karma 公开测试计划（索引）

本目录为 **对外公开** 的测试说明、复现方式与结果索引，随协议与版本迭代 **持续更新**。  
不包含私钥、未披露漏洞细节或私有风控规则；敏感内容遵循 [`SECURITY_DISCLOSURE.md`](../SECURITY_DISCLOSURE.md)。

---

## 1. 本目录内文档

| 文档 | 说明 |
|------|------|
| [simulation-and-cross-settlement.md](./simulation-and-cross-settlement.md) | 模拟 / 压测、账本守恒（如 Delta=0）、本地与生产数据库选型说明 |
| [attack-testing-roadmap.md](./attack-testing-roadmap.md) | 攻击面与安全测试路线图 + KSA/KSA2 回归索引 |
| [testnet-public-acceptance.md](./testnet-public-acceptance.md) | 测试网公开验收范围、与既有 Runbook 的对应关系及结果更新约定 |
| [TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md](./TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md) | **2026-05-17** 测试网预授权 + 全自动流水线验收摘要（353 项） |
| [STRESS_ATTACK_ACCEPTANCE_2026-05-17.md](./STRESS_ATTACK_ACCEPTANCE_2026-05-17.md) | **2026-05-17** 压力 + 攻击测试摘要（3,143 项；MEDIUM 修复说明） |
| [PHASE1_OPEN_WALLET_ACCEPTANCE.md](./PHASE1_OPEN_WALLET_ACCEPTANCE.md) | **Phase 1** Open Wallet / TradeLaunch EIP-712 验收摘要与复测表 |

---

## 2. 仓库内其他公开测试相关文档（交叉引用）

| 主题 | 路径 |
|------|------|
| Phase 4 结构压测（本地、确定性） | [`STRESS_TEST_RUNBOOK.md`](../STRESS_TEST_RUNBOOK.md) |
| Phase 3 测试网最小链上路径 | [`TESTNET_RUNBOOK.md`](../TESTNET_RUNBOOK.md) |
| 测试网执行检查清单 | [`TESTNET_EXECUTION_CHECKLIST.md`](../TESTNET_EXECUTION_CHECKLIST.md) |
| 测试网集成检查清单 | [`testnet-integration-checklist.md`](../testnet-integration-checklist.md) |
| 公开 API / Runtime 加固与 E2E 对照说明 | [`testing-public-hardening.md`](../testing-public-hardening.md) |
| SDK 与本地/CI 测试命令 | [`sdk-quickstart.md`](../sdk-quickstart.md) |
| P0 验收跑书（中文） | [`PUBLIC_P0_ACCEPTANCE_RUNBOOK_CN.md`](../PUBLIC_P0_ACCEPTANCE_RUNBOOK_CN.md) |

---

## 3. 更新约定（维护者）

1. **版本与日期**：对外发布或重大测试轮次结束时，在对应子文档顶部更新 `> 最近更新：YYYY-MM-DD` 与简短变更说明。  
2. **结果存放**：可引用仓库内 `results/` 下 **已脱敏** 的聚合 JSON/摘要（若纳入版本控制）；原始大文件建议仅保留哈希或外链，避免仓库膨胀。  
3. **测试网**：链上交易哈希、合约地址、网络 ID 可公开；钱包私钥、RPC 内网地址 **不得** 写入本目录。  
4. **安全 / 攻击测试**：仅收录 **已修复或已公开披露** 的摘要与复现边界；未修复问题走负责任披露流程，不写入此处细节。

---

## 4. 公开结果索引（模板）

| 轮次 / 版本 | 类型 | 结论摘要 | 详细文档 / 工件 |
|-------------|------|----------|-----------------|
| `ee68f62` · 2026-05-17 | 测试网预授权 + Agent 自动执行 | 352/353 通过；Sepolia 7/7；0 CRITICAL/HIGH | [TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md](./TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md) |
| `ee68f62` · 2026-05-17 | 压力 + 攻击 | 3,143 项；27/30 攻击拦截；3 MEDIUM 已在公开仓加固 | [STRESS_ATTACK_ACCEPTANCE_2026-05-17.md](./STRESS_ATTACK_ACCEPTANCE_2026-05-17.md) |
| `84b9345` · 2026-05-18 | Open Wallet 贸易签名 | 公开 CI + `phase1_open_wallet_gate.sh` 绿；Sepolia 钱包 E2E 待填 | [PHASE1_OPEN_WALLET_ACCEPTANCE.md](./PHASE1_OPEN_WALLET_ACCEPTANCE.md) |
| （示例） | 交叉结算压测 | Delta=0，账本平衡 | 见 [simulation-and-cross-settlement.md](./simulation-and-cross-settlement.md) |
| 持续 | 测试网清单 | 与 Runbook 对齐 | [testnet-public-acceptance.md](./testnet-public-acceptance.md) |

维护者将上表作为「对外一句话结论」入口；细节一律落在子文档或已链接的 Runbook 中。
