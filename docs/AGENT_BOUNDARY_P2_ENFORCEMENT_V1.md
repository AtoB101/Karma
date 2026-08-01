# Karma Agent Boundary P2 Enforcement v1

> 标准目录：`packages/evidence-schema/agent-boundary.v1.json`  
> 确认策略：`packages/evidence-schema/human-confirmation-policy.v1.json`  
> 验真：`GET /v1/agents/{id}/boundary/verify`  
> 服务：`services/agent_boundary_verify.py`

## 目标（安全优先）

P1 完成身份/主人/签认入驻后，P2 保证**对端看到的边界与履约强制执行的边界一致**，且以现实行业确认为准：

1. 确认边界不可被商家自报放宽  
2. 责任签认绑定边界哈希；变更即失效  
3. 履约只允许在声明的 `scene_ids` / `service_specs` 内  
4. 高风险行业（金融/医疗）有独立场景策略，禁止静默回落全局默认  

## 强制规则

| 规则 | 行为 |
|------|------|
| 确认目录重算 | `save_agent_boundary` 用 human-confirmation-policy 重写 `confirmation_boundary` |
| 反放宽 | 若客户端提交比目录更松的 must_confirm → `AgentBoundaryError` |
| Ack 绑定 | `ack.boundary_hash == stored_hash == live_hash` 才算 `ack_bound_to_live_boundary` |
| 反治愈 | `GET /p1-status` / `refresh_p1_ready` **只**更新 `p1_ready`，不用 live hash 覆盖 `boundary_hash` |
| 变更失效 | 边界哈希变化且无新 ack → 旧 ack `acknowledged=false`，`invalidated_reason=boundary_changed` |
| 履约门闩 | `fulfill-intent` 前 `assert_seller_boundary_for_fulfill`（P1 + scene 覆盖 + 未放宽） |
| 对端验真 | `GET /boundary/verify?scene_id=` 返回 checks/gaps |

## 现实场景覆盖

确认策略 scenes 与 onboarding industries **一一对齐**（含 design/consulting/content/manufacturing/real_estate/financial/marketing/education/healthcare）。  
`financial_services`、`healthcare_medical` 标记 `high_risk=true`，接单默认 `OWNER_CONFIRM`。

## API

```bash
# 对端核验（可带 scene）
curl -s "$KARMA_API/v1/agents/$AGENT_ID/boundary/verify?scene_id=food_delivery"

# 读边界（无存档时 ephemeral=true，不落盘，防哈希漂移）
curl -s "$KARMA_API/v1/agents/$AGENT_ID/boundary"
```

## 与 P1 关系

- P1：你是谁、主人是谁、责任是否签认  
- P2：你能接什么单、哪些步骤必须人确认、对端如何核验且履约强制  

## 相关

- `docs/AGENT_BOUNDARY_STANDARD_V1.md`
- `docs/AGENT_P1_ONBOARDING_V1.md`
- `docs/HUMAN_CONFIRMATION_POLICY_V1.md`
