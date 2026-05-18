# AP2 ↔ Karma Evidence 字段映射（Phase 3）

> **版本：** `agents-to-payments/ap2-mandate/v1` ↔ `karma.ta.evidence_bundle.v1`  
> **实现：** `trusted_agent_runtime/ap2_adapter.py`

## 1. 三层 Mandate 模型

| AP2 层 | Karma 来源 | 说明 |
|--------|-----------|------|
| **Intent Mandate** | `task_id` + `user_goal_hash` | 用户/代理意图锚点（不含明文载荷） |
| **Cart Mandate** | `receipt_hashes[]` + `merchant_ref` | 执行步骤哈希链 + 商户订单号 |
| **Payment Mandate** | PaymentIntent 字段 | `payer` / `payee` / `token` / `amount` / `chainId` / `policyId` / `expiresAt` |

## 2. 核心 digest 字段

| 字段 | 算法 | 稳定性要求 |
|------|------|------------|
| `karma_evidence_digest` | `SHA-256(canonical_json(bundle))` | 往返转换不得改变 |
| `mandate_digest` | `SHA-256(canonical_json(mandate \\ {mandate_signature}))` | AP2 侧完整性 |

Canonical JSON：`sort_keys=True`, `separators=(",", ":")`（见 `trusted_agent_runtime/hashing.py`）。

## 3. EvidenceBundle ↔ AP2 映射表

| Karma (`EvidenceBundle`) | AP2 字段 |
|--------------------------|----------|
| `bundle_id` | `karma_bundle_id` |
| `task_id` | `karma_task_id` / `intent_mandate.intent_id`（可派生） |
| `task_contract_hash` | `cart_mandate.task_contract_hash` |
| `receipt_hashes[]` | `cart_mandate.line_item_hashes[]` |
| `final_result_hash` | 末项 `line_item_hashes` 或独立披露 |
| `agent_signature` | `mandate_signature`（可选） |
| `created_at` | `intent_mandate.created_at` |

## 4. PaymentIntent 生命周期

| PaymentIntent.status | 触发条件 |
|---------------------|----------|
| `created` | `POST /v1/payment-intents` |
| `authorized` | 绑定 `taskId` 或 `voucherId`（`POST .../bind`） |
| `settled` | 关联 `task_id` 进入 settlement `SETTLED` |
| `expired` | 超过 `expiresAt`（`expire_stale_intents`） |
| `cancelled` | 预留（手动取消 API 可后续扩展） |

## 5. Human-Not-Present 模式

| 策略字段 | 默认 | HNP 开启时 |
|----------|------|------------|
| `human_not_present_allowed` | `false` | 需 `auto_enabled` + `responsibility_acknowledged` |
| `single_limit` | 操作员配置 | ≤ **50** USDC（等值口径） |
| `daily_limit` | 操作员配置 | ≤ **200** USDC |
| 有效支出乘数 | 1.0 | **0.5×**（`effective_spending_limits`） |

## 6. SD-JWT 公开验证

导出格式：`karma-sd-jwt+v1.<payload_b64url>.<digest_b64url>`

```bash
# Python 一键验证（仓库根目录）
python -c "
from services.evidence_export import verify_sd_jwt_export
import sys
ok, payload, detail = verify_sd_jwt_export(sys.argv[1])
print('ok=', ok, 'detail=', detail, 'merchant_ref=', payload.get('merchant_ref'))
" 'YOUR_TOKEN_HERE'
```

## 7. 外部验证 API

- `POST /v1/evidence/{evidenceId}/verify-external` — 校验 AP2 mandate 与存储 bundle digest  
- `POST /v1/evidence/{evidenceId}/verify` — 校验 `expectedDigestSha256`  
- `GET /v1/evidence/{evidenceId}` — OpenAPI `EvidenceObject`

私有仓风险分 **不** 进入上述公开 schema（见路线图 §6.3）。
