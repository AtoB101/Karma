# 攻击面与安全测试（公开路线图）

> 最近更新：2026-05-13  
> 状态：**路线图与占位** — 执行记录与结论将随轮次在此文档补充。

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
| — | — | （待首次公开轮次填写） | — | — |

---

## 4. 与现有安全文档的关系

- 总览与检查清单：[`SECURITY_AUDIT_2026.md`](../SECURITY_AUDIT_2026.md)、[`PRODUCT_SECURITY_REQUIREMENTS.md`](../PRODUCT_SECURITY_REQUIREMENTS.md)  
- Agent Guard 与门户：[`AGENT_GUARD_SECURITY_HARDENING.md`](../AGENT_GUARD_SECURITY_HARDENING.md)  

本文件侧重 **「对外可读的测试计划与轮次结果」**；详细技术条款以上述专题文档为准。
