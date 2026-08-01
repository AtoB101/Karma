# Karma Important Fields P5 v1 — 字段锁定

> 目录：`packages/evidence-schema/important-fields-standard.v1.json`  
> 加密：`services/important_fields_crypto.py`  
> 捕获/三方：`services/important_fields_capture.py`  
> 精密度：`services/important_fields_standard.py`  
> 履约闸门：`services/intent_fulfillment.py`  
> API：`/v1/standards/important-fields/*`

## 目标（真实需求）

成交前必须把「验什么」锁死：金额、时限、验收标准、场景关键字段。  
越精细越不容易后期扯皮；加密与三方一致是为了防中间篡改、防单方伪造、防买卖双方串谋刷一致。

## 安全模型

| 机制 | 标准 |
|------|------|
| 信封 | `karma2.` AES-256-GCM（`karma1.` 仅遗留解密） |
| 密钥 | `KARMA_IMPORTANT_FIELDS_KEY` + HKDF；**按 capture + role 分密钥** |
| AAD | `capture_id\|scene_id\|role\|protocol_fields_hash`（防拼接/换角色） |
| 协议锁定 | 交互中抓取 → `protocol_fields_hash` + HMAC |
| 三方一致 | `buyer_hash == seller_hash == protocol_hash` → `MATCHED` 并 **封存** |
| 防串谋 | 角色绑定 `buyer_agent_id`/`seller_agent_id`；两侧 `submitter_agent_id` 必须不同 |
| 防重放 | nonce 一次性 + attempt budget |
| 履约绑定 | `require_matched_capture` 校验 `interaction_ref` + `expected_amount` |

生产 / staging **必须**设置 `KARMA_IMPORTANT_FIELDS_KEY`（推荐 64 位 hex）。

## 精密度（hash 前规范化）

- **金额**：十进制字符串；`18.50` / `18.5` / `18.5000` → 同一 hash  
- **时间**：ISO-8601 → UTC 秒精度 `YYYY-MM-DDTHH:MM:SSZ`  
- **文本**：Unicode NFC + trim  

格式噪声不得制造假 MATCHED，也不得制造无意义 COUNTERED。

## Agent 用法

```text
POST …/captures
  {scene_id, interaction_ref, extracted_fields,
   buyer_agent_id, seller_agent_id}
→ capture_id + protocol_fields_hash

GET  …/captures/{id}/session-key?role=buyer|seller   (TLS+auth)
POST …/encrypt  {capture_id, role, fields}           (可信 helper)
POST …/submit-encrypted
  {capture_id, role, ciphertext: "karma2.…", nonce, submitter_agent_id}
POST …/match-secure → MATCHED (sealed)

fulfill-intent + important_fields_capture_id
  （校验 scene / interaction_ref / amount）
```

高风险场景禁止 demo `auto_lock`；开发环境非高风险可用 `auto_lock_important_fields=true`（仍走角色分密钥 + 双侧提交）。

## 与前后盘

| 盘 | 作用 |
|----|------|
| P4 | 主人确认「是否成交」 |
| **P5** | 加密锁定「成交字段」并三方封存 |
| P6 | 接单履约对照已锁定字段 |

## 相关

- `docs/IMPORTANT_FIELDS_STANDARD_V1.md`
- `docs/HUMAN_CONFIRMATION_P4_V1.md`
- `docs/REAL_SCENARIO_LOOP_V1.md`
