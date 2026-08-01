# Karma Settlement & Reputation P8 v1

> 目录：`packages/evidence-schema/settlement-reputation.v1.json`  
> 服务：`services/settlement_reputation.py`  
> API：`/v1/settlement-reputation/*` · `GET /v1/standards/settlement-reputation`  
> 接线：`buyer-accept` / `auto-confirm` 结算后封存证明

## 目标

按行业真实差异做结算；Agent 在验真通过后智能代验，节省用户时间。  
对公**可核验、不明文**：公开承诺哈希；明细 `karma2` 加密，当事人/监管可解密审计。  
隐私绝对保护与监管审计、公信力并存。

## 行业结算差异（摘）

| 场景 | 模式 | Agent 代验 | 确认 |
|------|------|------------|------|
| 外卖 / 叫车 | 验真后即时 | 是 | POLICY_AUTO |
| 机票 | 出票凭证后 | 是 | POLICY_AUTO |
| 酒店 / 教育 | 回执后 | 否 | OWNER_CONFIRM |
| 企业采购 / 制造 | 发票验收窗 | 否 | OWNER_CONFIRM |
| API / 数据 | 计量即时 | 是 | POLICY_AUTO |
| 金融 / 医疗 | 延迟显式 | **禁止** | OWNER_CONFIRM |

## 公开透明 ≠ 明文可查

```text
公开：
  attestation_id, scene_id, outcome,
  outcome_commitment, scope_hash, proof_hash,
  reputation_delta_commitment, settled_at

加密（karma2，角色分密钥）：
  parties / regulator / protocol
  → 金额、当事人 agent_id、capture、审计回溯链
```

任何人可 `verify-commitment` 核对承诺；  
只有持角色密钥者可 `decrypt` 审计明细（生产需再加鉴权）。

## Agent 智能验证

```text
POST /v1/settlement-reputation/agent-auto-verify
→ allowed=true 时，Agent 可在 P7 VERIFIED 后代用户走结算
→ 高风险场景永远 allowed=false
```

## 结算后

1. 场景化信誉增量（公开侧为 commitment）  
2. 全局 reputation 更新（既有）  
3. 封存 attestation（公开承诺 + 三份密文）  
4. 过渡审计表继续记录流程状态（无 PII）

## 与前后盘

| 盘 | 作用 |
|----|------|
| P4–P7 | 确认 / 字段锁 / 接单责任 / 交付验真 |
| **P8** | 差异化结算 + 加密可查证明 + 场景信誉 |
| 后续 | 链上 attestation / 监管专网密钥分发 |

## 相关

- `docs/DELIVERY_VERIFICATION_P7_V1.md`
- `docs/IMPORTANT_FIELDS_P5_V1.md`
- `docs/TRUST_ENGINE_V1_PUBLIC_SCHEMA.md`
- `docs/SETTLEMENT_FLOW_PUBLIC.md`
