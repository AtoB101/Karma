# Karma2 私有仓能力补齐清单（Phase 1–3）

> **生成时间（UTC）：** {{GENERATED_AT_UTC}}  
> **公开基线 commit：** `{{CORE_COMMIT}}`（仓库 {{CORE_REPO}}）  
> **用途：** 公开仓合并 Phase 1–3 后，私仓在同一发布窗口逐项勾选；**不得**将私有逻辑回灌公开仓。  
> **配套：** [`PRIVATE_REPO_EXECUTION_CHECKLIST-zh.md`](https://github.com/AtoB101/Karma/blob/main/docs/PRIVATE_REPO_EXECUTION_CHECKLIST-zh.md) · [`SYNC_PRIVATE_RUNTIME.md`](https://github.com/AtoB101/Karma/blob/main/docs/SYNC_PRIVATE_RUNTIME.md)

---

## 一、锁步发布（每次公开 `main` 合并后必做）

| # | 动作 | 通过标准 | ☐ |
|---|------|----------|---|
| L1 | 更新 `CORE_VERSION.lock` | `core.commit` == `{{CORE_COMMIT}}` | |
| L2 | 刷新同步包 | `./split-release/prepare-karma2-sync-package.sh --core-commit {{CORE_COMMIT}}` | |
| L3 | 刷新 `vendor/karma-public-sync/` | 来自同步包输出，禁止手改 vendor | |
| L4 | 更新 `deployment-manifest.json` | 链 ID、合约地址、ABI 哈希与链上一致 | |
| L5 | `./verify-manifest.sh` + Lockstep CI | 绿 | |
| L6 | 合同回归 | `run_public_contract_sync_tests` / `run_schema_contract_tests`（OpenAPI/schema 有变时） | |

**本次基线合同面（`{{CORE_COMMIT}}` 起）：**

- OpenAPI：`/v1/payment-intents`、`/v1/evidence/*`（含 `verify-external`）
- Schema：`PaymentIntent`、`CreatePaymentIntentRequest`；`human_not_present_allowed`
- 迁移认知：`0026`（x402 `funding_source`）、`0027`（`payment_intents`）、`0028`（`human_not_present_allowed`）

---

## 二、公开仓统一验收（托管公开 API 的环境建议跑）

| 顺序 | 脚本 | ☐ |
|------|------|---|
| 1 | `bash scripts/acceptance/phase1_open_wallet_gate.sh` | |
| 2 | `bash scripts/acceptance/phase2_x402_gate.sh` | |
| 3 | `bash scripts/acceptance/phase3_ap2_gate.sh` | |
| 4 | `bash scripts/run_public_acceptance_tests.sh -q --tb=short` | |

公开侧仍待**人工签字**的项见：`docs/public-testing/PHASE1_OPEN_WALLET_ACCEPTANCE.md`、`PHASE2_X402_ACCEPTANCE.md`、`PHASE3_AP2_ACCEPTANCE.md`。

---

## 三、Phase 1 — Open Wallet / 预授权（私仓补齐）

| # | 能力 | 说明 | ☐ |
|---|------|------|---|
| P1-1 | `SigningBackend` 私有实现 | KMS/HSM 子类；trade launch / voucher | |
| P1-2 | 链上 createBill / 付款码锚定 | `voucher_id` / `chain_anchor_hash` / txHash 索引 | |
| P1-3 | BillManager / LockPool **源码** | 仅私仓；公开为 ABI 快照 | |
| P1-4 | CircuitBreaker + Safe | `createBill` 强制；Admin → Gnosis Safe | |
| P1-5 | 预授权不绕过风控 | 自动 pipeline 仍走私有 `POST /v1/verify` | |
| P1-6 | OpenClaw webhook（可选） | `voucher.*`、`settlement.settled` | |
| P1-7 | 内部 SOP | 传统 vs 预授权（链到公开 Console 文档） | |

参考：公开 `docs/PRIVATE_REPO_PHASE1_CHECKLIST-zh.md`

---

## 四、Phase 2 — x402（私仓补齐 / 运维）

| # | 能力 | 说明 | ☐ |
|---|------|------|---|
| P2-1 | 测试网密钥与 RPC | `TESTNET_*`、鉴权 RPC；`X402_PAYMENT_BACKEND=sepolia` | |
| P2-2 | x402 实机签字 | env 签名、Sepolia USDC、OpenClaw `karma_x402_fetch` | |
| P2-3 | 可选 fork `sdk/x402` | 企业内部 URL/对账策略 | |
| P2-4 | 审计对账 | `external_payment` + `funding_source` → 私有 BI / 争议材料 | |

---

## 五、Phase 3 — AP2 / PaymentIntent（私仓**核心**补齐）

| # | 能力 | 说明 | ☐ |
|---|------|------|---|
| P3-1 | 私有 `/v1/verify` 扩展 | AP2 Intent / PaymentIntent **风险分、反作弊、争议权重**（不进公开 schema） | |
| P3-2 | AP2 风险规则 | `merchant_ref` / `policy_id` / `human_not_present` 拦截与限额 | |
| P3-3 | Human-not-present 运营 | 公开已限 50/200 + 0.5×；私仓可加 KYA、设备指纹、商户名单 | |
| P3-4 | PaymentIntent ↔ 账单 | `merchantRef` ↔ BillManager / escrow 对账 | |
| P3-5 | SD-JWT / mandate 争议材料 | 消费公开 `sd_jwt_export` + `ap2_mandate` 作仲裁附件 | |
| P3-6 | 私仓 E2E | PaymentIntent → bind task → 公开 SETTLED → 私有 verify 仍通过 | |

**公开已实现（私仓勿重复建设）：** `trusted_agent_runtime/ap2_adapter.py`、`services/evidence_export.py`、Payment Intent API、公开 `verify-external`。

映射文档：公开 `docs/AP2_EVIDENCE_PROFILE-zh.md`

---

## 六、私有运行时与基础设施（持续）

| # | 组件 | ☐ |
|---|------|---|
| R1 | Private Risk Runtime（评分、洗单、争议权重） | |
| R2 | `PRIVATE_RUNTIME_API_KEY`（公开 API → 私有 verify） | |
| R3 | Celery / Worker（私仓自建） | |
| R4 | MinIO/S3 敏感证据访问控制 | |
| R5 | 生产网络隔离（verify 内网/localhost） | |

---

## 七、商业 / 合规目录（私仓）

| 路径 | 内容 | ☐ |
|------|------|---|
| `commercial/` | 客户 Runbook、报价；轻 KYC/fiat（Phase 5） | |
| `outreach/` | 合作方记录 | |
| `ops/incident/` | 未公开 IR | |
| `investor/` | 融资材料（禁止进公开 git） | |

---

## 八、生产发布 60 秒核对

- [ ] `CORE_VERSION.lock` == `{{CORE_COMMIT}}`（或当前要跑的公开 commit）
- [ ] `verify-manifest.sh` 通过
- [ ] 无私钥进 PR diff
- [ ] 私有 verify 冒烟 + 一笔 testnet 结算
- [ ] 若托管公开 API：`APP_ENV=production` 闸门全开
- [ ] 回滚用上一版 `deployment-manifest.json` 已归档

---

## 九、建议 Sprint 顺序（合并 Phase 3 后）

1. **锁步 L1–L6**（机械步骤）  
2. **合同同步测试**  
3. **P3-1 + P3-2**（AP2 风控 — Phase 3 私仓价值）  
4. **P1-2 + P1-3**（真链上付款码，若产品需要）  
5. **P2-2**（x402 测试网签字）  
6. Phase 4 前置（policy-as-code、Mandate 链）

---

## 十、签字

| 角色 | Phase 1 | Phase 2 x402 | Phase 3 AP2 | 锁步 `{{CORE_COMMIT}}` |
|------|---------|--------------|-------------|-------------------------|
| 私有仓 Owner | | | | |
| 链上/合约 | | | — | |
| 风控 | | | | |
| 运维/OpenClaw | | | | |

---

*本文件由 `prepare-karma2-sync-package.sh` 从公开仓模板生成；勿在 Karma2 手改后当作公开真源。*
