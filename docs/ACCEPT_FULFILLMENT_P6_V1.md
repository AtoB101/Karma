# Karma Accept & Fulfillment P6 v1

> 目录：`packages/evidence-schema/accept-fulfillment.v1.json`  
> 服务：`services/accept_fulfillment.py`  
> 确认 TTL：`services/human_confirmation_policy.py`  
> 履约：`services/intent_fulfillment.py`  
> API：`/v1/standards/accept-fulfillment*` · `POST /v1/confirmations/expire-pending-seller-accepts`

## 目标（真实需求）

卖方接单必须有时限：超时自动取消，多次未确认记入档案。  
确认接单后即产生违约赔偿责任。长期多次未确认的卖家：验证更严、责任金更高、信誉小幅下调，并在发现排序中靠后。

## 场景时限（示例）

| 场景 | 接单 TTL | 超时后 | 确认后补偿（基础） |
|------|----------|--------|-------------------|
| 叫车 | 120s | 取消并重新匹配 | 10% + 责任金 |
| 外卖 | 300s | 取消并重新匹配 | 8% |
| 酒店 / 机票 | 900s | 取消意向 | 15–20% |
| 企业采购 | 24h | 取消意向 | 20% + 更高责任金 |
| 金融 / 医疗 | 短–中 | 取消；强制人工确认 | 30%+ |

未确认达到 3 / 7 / 15 次：验证档 elevated → strict → restricted，责任金乘数 1.5 / 2.5 / 4.0，TTL 缩短。

## 状态机

```text
awaiting_seller_confirmation (TTL)
  → Yes  → liability_armed → voucher / settle
  → No   → cancelled_seller_reject + non_confirm++ + 信誉小幅−
  → TTL  → cancelled_seller_timeout + non_confirm++ + 信誉小幅−
  → N×   → verification_tier↑ · bond↑ · discovery demote
```

## Agent 用法

```text
fulfill-intent → awaiting_seller_confirmation
  （含 seller_accept_ttl_seconds + seller_risk）
decide(confirm=true) → fulfill-intent + seller_confirmation_session_id
  → response.breach_liability（责任金/补偿 bps 已武装）

超时：
  GET session / POST expire-pending-seller-accepts / 再次 fulfill
  → status=cancelled_seller_timeout
```

## 与前后盘

| 盘 | 作用 |
|----|------|
| P4 | 是否确认接单 |
| P5 | 锁定成交字段 |
| **P6** | 接单时限、未确认档案、确认后违约责任 |
| P7 | 交付验真对照已锁字段与责任条款 |

## 相关

- `docs/HUMAN_CONFIRMATION_P4_V1.md`
- `docs/IMPORTANT_FIELDS_P5_V1.md`
- `docs/REAL_SCENARIO_LOOP_V1.md`
