# 攻击面与安全测试（公开路线图）

> 最近更新：2026-05-14  
> 状态：**路线图** — 已补充一轮模拟攻击的公开缓解摘要；后续轮次在此增量更新。

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
| 模拟攻击清单（KSA） | 2026-05-14 | 30 场景 / 7 项漏洞（公开仓库可修复子集） | 见下表「已落地缓解」 | 本仓库 `services/task_contract_guard.py`、`api/app.py`、`api/routes/*` |

### 3.1 已落地缓解（公开仓库）

| ID | 说明 | 缓解方式 |
|----|------|----------|
| **KSA-030** | `POST /v1/security/*` 与 `POST/GET /v1/admin/*` 在关闭全局鉴权时仍可匿名写入 | `/v1/security`、`/v1/admin` 路由改为 **始终** 要求 `Bearer` 或 `X-Karma-Api-Key`（`get_current_agent_id`） |
| **KSA-011** | 对不存在 `task_id` 提交 Execution Receipt 仍被接受 | `POST /v1/receipts` 与 `POST /runtime/submit-receipt` 在持久化前 **`ensure_task_contract_exists`**；`POST /v1/settlement/create` 同样要求已存在任务合约 |
| **KSA-028** | 买方将自身设为 worker（自买自卖） | `POST .../settlement/.../lock` 与 `PATCH /v1/contracts/{id}/assign` 拒绝 `worker == buyer/client` |
| **KSA-023** | 超大自由文本 / JSON 导致内存压力 | `CreateContractRequest` / `RegisterAgentRequest` 增加 **长度与 JSON 体积** 上限；`expected_output_schema` 序列化 ≤ 65536 字节 |
| **KSA-001** | 批量虚假注册 | `POST /v1/agents` 增加 **`register_rate_limit`** 依赖 |
| **KSA-010** | 过久时间戳的执行回执仍被接受 | **仅执行回执** `validate_execution_receipt_static` 在 `receipt_strict_recent_timestamps=true` 时使用 `receipt_max_past_hours_strict`（默认 24h）；进度回执仍用宽松 `receipt_max_past_hours` 以支持超时确认等场景 |
| **KSA-029** | 循环结算 A→B→C→A | **未在 API 层做图环检测**（易误伤合法背对背双边任务）；保留为路线图项，可与链上/风控层协同 |

回归用例：`tests/unit/test_security_attack_mitigations.py`。

---

## 4. 与现有安全文档的关系

- 总览与检查清单：[`SECURITY_AUDIT_2026.md`](../SECURITY_AUDIT_2026.md)、[`PRODUCT_SECURITY_REQUIREMENTS.md`](../PRODUCT_SECURITY_REQUIREMENTS.md)  
- Agent Guard 与门户：[`AGENT_GUARD_SECURITY_HARDENING.md`](../AGENT_GUARD_SECURITY_HARDENING.md)  

本文件侧重 **「对外可读的测试计划与轮次结果」**；详细技术条款以上述专题文档为准。
