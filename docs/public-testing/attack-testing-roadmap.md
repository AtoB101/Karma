# 攻击面与安全测试（公开路线图）

> 最近更新：2026-05-18  
> 状态：**路线图 + 验收摘要** — 见 [PHASE1_OPEN_WALLET_ACCEPTANCE.md](./PHASE1_OPEN_WALLET_ACCEPTANCE.md)、[STRESS_ATTACK_ACCEPTANCE_2026-05-17.md](./STRESS_ATTACK_ACCEPTANCE_2026-05-17.md)、[TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md](./TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md)。

---

## 1. 公开范围说明

本文件仅收录 **计划维度** 与 **已结束且可公开** 的测试摘要（不含利用细节、未修复 0-day、内部权重与私有风控规则）。  
漏洞提交请遵循 [`SECURITY_DISCLOSURE.md`](../SECURITY_DISCLOSURE.md)。

---

## 2. 计划中的测试类别（后续逐项落地）

| 类别 | 目标 | 备注 |
|------|------|------|
| **认证与授权** | API Key / JWT / Runtime Key / 钱包绑定路径滥用、越权 | 与 [`API_AUTH.md`](../API_AUTH.md) 对齐 |
| **速率与滥用** | 写路径限流、重放、幂等键 | 参见 `api/middleware/rate_limit.py` 与加固文档 |
| **输入与协议边界** | 畸形 JSON、超大 body、路径参数注入 | 与 `validate_public_url_segment` 等护栏一致 |
| **结算与状态机** | 非法转移、双花意图、顺序绕过 | 与 [`SETTLEMENT_FLOW_PUBLIC.md`](../SETTLEMENT_FLOW_PUBLIC.md) 对照 |
| **依赖与供应链** | 第三方库 CVE、CI 完整性 | 与 [`SECURITY_RELEASE_GATES.md`](../SECURITY_RELEASE_GATES.md) 协同 |

---

## 3. 公开结果记录（模板）

| 轮次 | 日期 | 范围摘要 | 结论 / 风险等级 | 关联 PR / 文档 |
|------|------|----------|-----------------|----------------|
| **全量压力 + 攻击** | 2026-05-17 | 3,143 项；30 攻击场景；500 并发 | **0 CRITICAL/HIGH**；3 MEDIUM → 公开仓加固 | [STRESS_ATTACK_ACCEPTANCE_2026-05-17.md](./STRESS_ATTACK_ACCEPTANCE_2026-05-17.md) |
| **测试网预授权 E2E** | 2026-05-17 | 353 项；Sepolia 7/7；预授权流水线 | **99.7%**；0 CRITICAL/HIGH | [TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md](./TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md) |
| **Phase 1 Open Wallet 签名** | 2026-05-18 | TradeLaunch EIP-712 + voucher attestation 统一 | CI 专项通过；预发见验收表 | [PHASE1_OPEN_WALLET_ACCEPTANCE.md](./PHASE1_OPEN_WALLET_ACCEPTANCE.md) |
| 模拟攻击清单（KSA） | 2026-05-14 | 30 场景 / 7 项漏洞（公开仓库可修复子集） | 见下表「已落地缓解」 | 本仓库 `services/task_contract_guard.py`、`api/app.py`、`api/routes/*` |
| Level 2（KSA2） | 2026-05-13 | 38 场景 / 4 项漏洞（公开仓库可修复子集） | 见下表「Level 2 已落地缓解」 | `services/settlement_receipt_release_guard.py`、`services/settlement_cycle_guard.py`、`services/text_safety.py` |

### 3.1 已落地缓解（公开仓库）

| ID | 说明 | 缓解方式 |
|----|------|----------|
| **KSA-030** | `POST /v1/security/*` 与 `POST/GET /v1/admin/*` 在关闭全局鉴权时仍可匿名写入 | `/v1/security`、`/v1/admin` 路由改为 **始终** 要求 `Bearer` 或 `X-Karma-Api-Key`（`get_current_agent_id`） |
| **KSA-011** | 对不存在 `task_id` 提交 Execution Receipt 仍被接受 | `POST /v1/receipts` 与 `POST /runtime/submit-receipt` 在持久化前 **`ensure_task_contract_exists`**；`POST /v1/settlement/create` 同样要求已存在任务合约 |
| **KSA-028** | 买方将自身设为 worker（自买自卖） | `POST .../settlement/.../lock` 与 `PATCH /v1/contracts/{id}/assign` 拒绝 `worker == buyer/client` |
| **KSA-023** | 超大自由文本 / JSON 导致内存压力 | `CreateContractRequest` / `RegisterAgentRequest` 增加 **长度与 JSON 体积** 上限；`expected_output_schema` 序列化 ≤ 65536 字节 |
| **KSA-001** | 批量虚假注册 | `POST /v1/agents` 使用 **`register_agent_rate_limit`**；Redis 不可用时 **进程内滑动窗口兜底**（2026-05-17） |
| **KSA-010** | 过久时间戳的执行回执仍被接受 | **仅执行回执** `validate_execution_receipt_static` 在 `receipt_strict_recent_timestamps=true` 时使用 `receipt_max_past_hours_strict`（默认 24h）；进度回执仍用宽松 `receipt_max_past_hours` 以支持超时确认等场景 |
| **KSA-029** | 循环结算 A→B→C→A | 与 **KSA2-034** 互补；三角环 `A→B→C→A` 由 `assert_lock_does_not_close_payment_cycle` 拦截（`tests/integration/test_triangle_settlement_cycle.py`） |

### 3.2 Phase 1 贸易启动签名（KSA-TL）

| ID | 说明 | 缓解方式 |
|----|------|----------|
| **KSA-TL-001** | 无 EIP-712 或占位符 `buyer_signature` 仍可 launch | `TRADE_LAUNCH_REQUIRE_EIP712=true`（生产启动校验）+ `verify_trade_launch_commitment` |
| **KSA-TL-002** | 签名钱包与绑定 `karma_identity_id` 不一致 | recover 地址必须等于 `IdentityProfile.bound_wallet_address` |
| **KSA-TL-003** | 过期 `deadline_unix` 仍接受 | launch 前校验 `now <= deadline_unix` |
| **KSA-TL-004** | launch 金额绕过 `daily_limit` | `assert_pre_launch_spending_policy` + 可选 `trade_launch_record_runtime_daily_spend` |
| **KSA-TL-005** | TradeLaunch 签与 voucher AuthorizationVoucher 语义割裂 | `trade_launch_attestation` + `voucher_buyer_commitment` 双路径统一 |

### 3.3 Level 2 已落地缓解（KSA2）

| ID | 说明 | 缓解方式 |
|----|------|----------|
| **KSA2-006** | 无执行回执即可向卖方释放资金（如 `partial` 在 0% 已确认进度下全额结算） | **`ensure_success_execution_receipt_before_seller_payout`**：`settled_amount > 0` 时要求任务上至少一条 **SUCCESS** 执行回执；适用于 `partial`、`regret`、`auto-arbitrate`、`buyer-accept`（默认 `settlement_requires_success_execution_receipt_for_seller_release=true`） |
| **KSA2-008** | RLO / 双向排版控制符（如 U+202E）原样入库 | **`validate_safe_storage_text`**：拒绝 U+202A–U+202E、U+2066–U+2069；用于合约标题/描述、Agent 名称、Voucher 字符串字段、结算 `reason` 等 |
| **KSA2-011** | NUL（`\x00`）原样入库 | 同上 **禁止 NUL**；`expected_output_schema` 内嵌字符串经 **`validate_json_strings_safe`** 校验 |
| **KSA2-034** | 多买方链式锁单形成有向环（如 A→B→…→A） | **`assert_lock_does_not_close_payment_cycle`**：在 `lock` 前于 **非终态** 结算上检测 `worker` 是否已可达 `buyer`；默认 `settlement_block_buyer_worker_payment_cycle=true`（与 KSA-029「全图环」不同，此为 **轻量、可解释** 的锁前护栏） |

| **KSA-010b** | 同任务执行回执 `started_at` 早于上一笔 | `POST /v1/receipts` 拒绝 `started_at < latest.started_at`（2026-05-17） |

### 3.4 Phase 2 x402（KSA-X402）

| ID | 说明 | 缓解方式 |
|----|------|----------|
| **KSA-X402-001** | 超额预算仍发起支付 | `assert_budget` + API `x402_hard_max_budget_usdc` |
| **KSA-X402-002** | 402 resource 与请求 URL 不一致（钓鱼） | `assert_resource_matches_url` |
| **KSA-X402-003** | 路径遍历 / 内网 SSRF | `validate_x402_target_url`；生产关闭 `X402_ALLOW_PRIVATE_HOSTS` |
| **KSA-X402-004** | 重复 402 无限重试 | 客户端单次 pay + 单次 retry（`payment_attempts`） |

回归用例：`tests/unit/test_x402_client.py`、`tests/unit/test_x402_security.py`、`tests/integration/test_x402_pay_and_fetch.py`。

---

回归用例（Phase 1 等）：`tests/unit/test_security_attack_mitigations.py`、`tests/unit/test_level2_attack_mitigations.py`、`tests/unit/test_settlement_cycle_guard.py`、`tests/integration/test_triangle_settlement_cycle.py`、`tests/unit/test_receipt_chronology.py`、`tests/unit/test_trade_launch_eip712.py`、`tests/unit/test_trade_launch_security.py`、`tests/unit/test_voucher_buyer_commitment.py`、`tests/integration/test_trade_launch_eip712_launch.py`。

---

## 4. 与现有安全文档的关系

- 总览与检查清单：[`SECURITY_AUDIT_2026.md`](../SECURITY_AUDIT_2026.md)、[`PRODUCT_SECURITY_REQUIREMENTS.md`](../PRODUCT_SECURITY_REQUIREMENTS.md)  
- Agent Guard 与门户：[`AGENT_GUARD_SECURITY_HARDENING.md`](../AGENT_GUARD_SECURITY_HARDENING.md)  

本文件侧重 **「对外可读的测试计划与轮次结果」**；详细技术条款以上述专题文档为准。
