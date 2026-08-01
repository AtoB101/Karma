# Karma Human Confirmation P4 v1

> 策略目录：`packages/evidence-schema/human-confirmation-policy.v1.json`  
> 服务：`services/human_confirmation_policy.py`  
> 履约：`services/intent_fulfillment.py`  
> API：`/v1/confirmations/*` · `POST /v1/orchestration/fulfill-intent`

## 目标（真实需求）

不同服务对「要不要问主人」不同：

| 类型 | 现实习惯 | P4 行为 |
|------|----------|---------|
| 外卖 / 叫车 | 结账时一次确认 | 买方只门闩 `accept_order` |
| 酒店 / 机票 | 先确认行程再锁价支付 | `select_offer` → `accept_order` |
| 企业采购 / 制造 | 选供应商与下 PO 都要人 | 买方两步 + **卖方** `accept_order` |
| 金融 / 医疗（高风险） | 不可静默自动 | 禁止 demo 关确认；禁止 POLICY_AUTO；强制 IF |

主人负担仍是 **是否确认**；Agent 只在必须点打扰。

## 买方履约步骤

```text
buyer_fulfill_confirm_steps(scene):
  日常消费 → [accept_order]
  住宿/出行票务/B2B/高风险/专业服务 → [select_offer, accept_order]
```

状态：`awaiting_owner_confirmation`，带 `confirmation_plan.next_required_step`。

## 卖方确认

当目录中 seller.`accept_order` = `OWNER_CONFIRM`（采购/制造/金融/医疗/软件/设计/咨询/房产等）：

→ `awaiting_seller_confirmation`  
→ `seller_confirmation_session_id` 恢复履约  

外卖/叫车等仍为 `POLICY_AUTO`（有商家预授权可自动接单）。

## 会话安全

- 忽略客户端 `policy_auto_allowed`（创建会话 /assert）  
- 绑定 owner、amount、scene/role/step、`interaction_ref`  
- TTL 30 分钟 → `EXPIRED`  
- 消费后 `USED`，不可重放  
- 未知 `scene_id` **拒绝**静默回落全局默认  

## 结算确认

`POST /v1/settlement/{task_id}/buyer-accept?scene_id=&confirmation_session_id=`  

仅当该场景 `buyer_accept_settle` 为 `OWNER_CONFIRM`（或高风险）时强制。

## Agent 用法

```text
fulfill-intent
  → awaiting_owner_confirmation (step=…)
  → decide(session, confirm=true, actor=buyer)
  → fulfill-intent + confirmation_session_id
  → (可选再一步买方 / IF / 卖方)
  → awaiting_seller_confirmation?
  → decide(actor=seller) + seller_confirmation_session_id
  → voucher → settle
```

## 与前后盘

| 盘 | 作用 |
|----|------|
| P2 | 确认边界不可被商家放宽 |
| P3 | 优先推荐边界清晰、信誉可核验的商家 |
| **P4** | 按真实场景只在关键点问主人是否确认 |
| P5 | Important Fields 三方锁定成交字段 |

## 相关

- `docs/HUMAN_CONFIRMATION_POLICY_V1.md`
- `docs/AGENT_BOUNDARY_P2_ENFORCEMENT_V1.md`
- `docs/DISCOVERY_PRIORITY_V1.md`
