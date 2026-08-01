# Karma Discovery Priority Standard v1（P3）

> 机器目录：`packages/evidence-schema/discovery-priority.v1.json`  
> HTTP：`GET /v1/standards/discovery-priority`  
> 发现：`POST /v1/discovery/intent` → `ranking.mode=priority+capability+trust`

## 目标

- 帮**用户**找到真正能解决该场景问题的商家  
- 帮**企业**找到靠谱、边界清晰、可核验的合作方  
- **安全优先**：身份/责任/边界可验证，再谈效率与价格感  
- **好质量 → 系统评分 → 信誉积累 → 长久合作**

## 优先级选择顺序（固定）

| 顺序 | 键 | 含义 |
|------|-----|------|
| 1 | `eligible` | 场景拒绝 / 未达硬门槛者剔除或垫底 |
| 2 | `p1_ready` | 身份类别、主人绑定、责任签认可核验 |
| 3 | `boundary_complete` | 能力/责任/确认边界完整可读 |
| 4 | `scene_covered` | `scene_ids` / `service_specs` 覆盖本次意图 |
| 5 | `trust_tier` | `proven` > `emerging` > `cold`（可验证结算记录） |
| 6 | `composite_score` | 能力匹配分 + 系统信任加分（场景权重） |

同分再比：`settled_volume` → `reputation_score` → `agent_id`。

## 分场景标准（摘录）

| 场景 | 特点 |
|------|------|
| 外卖 / 叫车 | 允许冷启动；场景覆盖与好评加分 |
| 机票 / 酒店 | 提高 proven 门槛；偏好 P1 |
| 企业采购 / 制造 | **强制** P1 + 完整边界 + 场景覆盖；禁止冷启动优先 |
| 金融 / 医疗（高风险） | 最严：P1 + 边界 + 场景覆盖 + 高成功率；冷启动不可推荐靠前 |

完整表见目录 JSON / `GET …/discovery-priority/scenes/{scene_id}`。

## 可验证评分基础

每个候选附带 `trust_evidence`：

- `reputation_score` / `settled_count` / `success_rate` / `dispute_rate`（库表聚合）  
- `p1_ready` / `boundary_hash`  
- `verify_urls`：`/p1-status`、`/trust`、`/boundary/verify?scene_id=`

助手与对端可复验，不盲信排序分。

## API 示例

```bash
# 标准说明
curl -s $KARMA_API/v1/standards/discovery-priority

# 发现（自动按意图场景套用优先级）
curl -s -X POST $KARMA_API/v1/discovery/intent \
  -H 'content-type: application/json' \
  -d '{"requirement_text":"帮我点一份披萨外卖","buyer_identity_id":"user-1","limit":5}'

# 企业采购：默认 enforce 场景门槛
curl -s -X POST $KARMA_API/v1/discovery/intent \
  -H 'content-type: application/json' \
  -d '{"requirement_text":"企业采购一批耗材","require_p1_ready":true,"limit":5}'
```

响应关注：

- `ranking.priority_order` / `ranking.scene_policy`  
- `recommended` + `recommendation_why`  
- 候选上的 `trust_tier`、`scene_covered`、`trust_evidence`

## 与前后盘关系

| 盘 | 作用 |
|----|------|
| P1 | 谁可被信任地入驻 |
| P2 | 边界是否真实、履约是否允许 |
| **P3** | 在合格集合里按优先级选出最能解决问题的一方 |
| P4+ | 确认、锁字段、履约、验真、结算反哺评分 |

## 相关

- `docs/AGENT_P1_ONBOARDING_V1.md`
- `docs/AGENT_BOUNDARY_P2_ENFORCEMENT_V1.md`
- `docs/HUMAN_CONFIRMATION_POLICY_V1.md`
- `docs/TRUST_ENGINE_V1_PUBLIC_SCHEMA.md`
