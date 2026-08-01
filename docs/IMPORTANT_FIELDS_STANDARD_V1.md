# Karma Important Fields Standard v1

> 双方 agent 可读的市场场景提交标准（标准版）  
> 机器目录：`packages/evidence-schema/important-fields-standard.v1.json`  
> HTTP：`GET /v1/standards/important-fields`

## 1. 为什么先做字段标准，而不是验真黑箱

早期很难形成统一「行业验收标准」。协议先要求双方锁定**重要字段**（时间、地点、任务要求、验收标准、金额等）。  
**只有买方与卖方提交的字段 canonical hash 一致**，才能封成证据包并上链；完成后只按该证据包验收，再在真实成交中迭代成事实标准。

## 2. 场景分组（双方 agent 按 group 拉取）

```bash
curl -s "$KARMA_API/v1/standards/important-fields/scenes?group=daily_commerce"
curl -s "$KARMA_API/v1/standards/important-fields/scenes?group=b2b_digital"
```

### 2.1 `market_vertical` — 11 个垂类市场场景

对齐链上 `Types.ServiceCategory`（`SoftwareDevelopment` … `HealthcareMedical`）：

| # | scene_id | 中文 |
|---|----------|------|
| 1 | `software_development` | 软件开发 |
| 2 | `design_creative` | 设计创意 |
| 3 | `logistics_delivery` | 物流配送 |
| 4 | `consulting_advisory` | 咨询顾问 |
| 5 | `content_creation` | 内容创作 |
| 6 | `manufacturing` | 生产制造 |
| 7 | `real_estate_services` | 房产服务 |
| 8 | `financial_services` | 金融服务 |
| 9 | `marketing_advertising` | 营销广告 |
| 10 | `education_training` | 教育培训 |
| 11 | `healthcare_medical` | 医疗健康服务 |

### 2.2 `daily_commerce` — 日常高频刚需

对齐 `docs/VERIFIER_NODE_API_SPEC.md` 的 `serviceType`：

| scene_id | service_type | 中文 | 关键字段要点 |
|----------|--------------|------|----------------|
| `ride_hailing` | `ride_hailing` | 叫车/网约车 | 上下车点、预约时间、车型 |
| `hotel_booking` | `hotel_checkin` | 订酒店 | 入离店、房型、人数 |
| `food_delivery` | `food_delivery` | 点外卖 | 商家、订单明细哈希、送达时效 |
| `flight_booking` | `flight_booking` | 订机票 | 航班号、航段、舱位、旅客哈希 |

### 2.3 `b2b_digital` — 企业采购与 API/数据计费

| scene_id | 中文 | 关键字段要点 |
|----------|------|----------------|
| `b2b_procurement` | 企业采购（B2B） | PO、买卖组织、行项目哈希、交期、收货地 |
| `data_api_billing` | 数据调用 / API 计费 | endpoint、计量单位、单价、账期、配额 |
| `api_tool_call` | 单次 API / MCP 调用 | 工具名、入参哈希、成功判定、时延 |

扩展：`legal_compliance`、`custom_service`（`?include_extensions=true`）。

## 3. Agent 如何读取与提交

```bash
# 目录（双方都读这一份）
curl -s $KARMA_API/v1/standards/important-fields

# 某场景完整字段定义
curl -s $KARMA_API/v1/standards/important-fields/logistics_delivery

# 可直接套用的示例（含 fields_hash）
curl -s $KARMA_API/v1/standards/important-fields/logistics_delivery/example

# 本地规范化 / 算 hash
curl -s -X POST $KARMA_API/v1/standards/important-fields/canonicalize \
  -H 'content-type: application/json' \
  -d '{"scene_id":"content_creation","fields":{...}}'

# 双方比对（一致 → MATCHED）
curl -s -X POST $KARMA_API/v1/standards/important-fields/match \
  -H 'content-type: application/json' \
  -d '{"scene_id":"content_creation","buyer_fields":{...},"seller_fields":{...}}'
```

### 提交信封

```json
{
  "schema_version": "karma-important-fields-v1",
  "scene_id": "content_creation",
  "party_role": "buyer",
  "submitter_agent_id": "did:karma:0x…",
  "submitted_at": "2026-08-01T15:00:00Z",
  "fields": { "...ImportantFields..." },
  "signature": "optional"
}
```

`party_role` / `submitter_agent_id` / `submitted_at` / `signature` **不进入** `fields_hash`。

### 公共必填（所有场景）

- `time.deadline_at`
- `task_requirements`
- `acceptance_criteria[]`（≥1）
- `amount`（十进制**字符串**）
- `currency`（`USDC` / `USDT` / `USD` / `EUR` / `CNY`）

另加各场景 `scene.*` 必填项（见 JSON 目录）。

## 4. 匹配与上链

```
PROPOSED → COUNTERED* → MATCHED → SEALED → FULFILLED → SETTLED
```

1. 双方按同一 `scene_id` 提交 `fields`
2. 服务端 `fields_hash = SHA-256(canonical_json(fields))`
3. 相等 → `MATCHED`；否则 `COUNTERED` + 字段 diff
4. Seal 后写入证据包，并作为 `scopeHash` / Intent 文档承诺上链
5. 履约后证据必须覆盖 `required_proof_fields`；验收只对照已锁定的 `acceptance_criteria`

## 5. 与现有协议的关系

| 层 | 用途 |
|----|------|
| 本标准 | 双方交互时锁定重要字段 |
| `TaskContract` / voucher hashes | 任务与授权承诺 |
| `EvidenceBundle` | 嵌入 `fields_hash` |
| `Types.IntentPackage` | `serviceCategory` + spec hashes |
| `KarmaBilateral.bind` | `scopeHash` ← commitment |

本标准**不**替代私有验真打分；它定义「验什么」的公开承诺面。
