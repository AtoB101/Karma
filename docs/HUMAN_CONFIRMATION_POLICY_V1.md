# Karma Human Confirmation Policy v1

> 机器目录：`packages/evidence-schema/human-confirmation-policy.v1.json`  
> HTTP：`GET /v1/standards/confirmation-policy`

## 目标

与 **Agent Boundary**（`docs/AGENT_BOUNDARY_STANDARD_V1.md`）配套：确认策略写入每个 agent 的 `confirmation_boundary`，对端可读。

把叫车 / 外卖 / 酒店 / 机票 / 采购 / API 等现实链路拆成：

| 类型 | 含义 | 主人负担 |
|------|------|----------|
| **AUTO** | 匹配、轨迹、证据上传、配额内调用 | 不打扰 |
| **OWNER_CONFIRM** | 选单、锁价、下单、取消、退款、改价 | 只答 **是否确认** |
| **POLICY_AUTO** | 有预授权/automation-policy 则可自动，否则降级为确认 | 按策略 |

Agent **不必逐步点流程**；只在必须确认点问一句 Yes/No。确认后即可接单或继续履约。

## 现实分流原则

**一定要人确认（钱 / 身份 / 不可逆）**

- 选择报价并下单（金额、地址、航班旅客、入住日期）
- 锁价 / 预授权 / 支付
- 取消、退改签、退款、售后
- 价格变动 / 动态加价
- 企业 PO 下达与收货付款
- 商家首次发布服务边界（onboarding）

**可以自动（执行与证明）**

- 发现与匹配商家/司机/运力
- 接单策略开启时的商家/司机接单
- 行程/配送轨迹、完单/签收证明哈希上传
- 配额内 API 调用与用量日志
- 预授权额度内的结算（POLICY_AUTO）

## 场景目录

| scene_id | 中文 |
|----------|------|
| `ride_hailing` | 叫车 |
| `food_delivery` | 外卖 |
| `hotel_booking` | 酒店 |
| `flight_booking` | 机票 |
| `b2b_procurement` | 企业采购 |
| `data_api_billing` | API/数据计费 |
| `api_tool_call` | 单次工具调用 |
| `logistics_delivery` | 物流 |
| `software_development` | 软件开发 |

与 Important Fields / onboarding `industry_id` 对齐。Discovery `task_type`（如 `commerce.food`）会映射到对应 `scene_id`。

## Agent UX 链路

```text
主人: 帮我点一份披萨
  ↓
agent POST /v1/orchestration/fulfill-intent
  → status=awaiting_owner_confirmation
  → owner_prompt_zh: 「是否确认下单？…」
  ↓
主人: 确认
  ↓
agent POST /v1/confirmations/sessions/{id}/decide  {"confirm": true}
  ↓
agent POST /v1/orchestration/fulfill-intent
       + confirmation_session_id
  → 接单 / 锁字段 / voucher / 执行
```

也可先规划再开会话：

```bash
# 看某场景买卖双方：哪些必须确认、哪些自动
curl -s $KARMA_API/v1/standards/confirmation-policy/scenes/food_delivery

# 生成 must_confirm / auto_ok 清单（可填 context 渲染提示语）
curl -s -X POST $KARMA_API/v1/confirmations/plan \
  -H 'content-type: application/json' \
  -d '{"scene_id":"food_delivery","role":"buyer","context":{"merchant":"面馆","amount":35,"currency":"USDC","address":"静安"}}'

# 开 Yes/No 会话
curl -s -X POST $KARMA_API/v1/confirmations/sessions \
  -H 'content-type: application/json' \
  -d '{"scene_id":"food_delivery","role":"buyer","step":"accept_order","owner_agent_id":"buyer-1","context":{"amount":35,"currency":"USDC"}}'

# 主人决定
curl -s -X POST $KARMA_API/v1/confirmations/sessions/cfm_xxx/decide \
  -H 'content-type: application/json' \
  -d '{"confirm":true,"actor_agent_id":"buyer-1"}'
```

## fulfill-intent 门闩

默认 `require_owner_confirmation=true`：

1. discover 完成后检查买方 `accept_order` 门闩  
2. 未确认 → **不创建 voucher**，返回 `awaiting_owner_confirmation`  
3. 已确认会话 → 继续 negotiate → voucher → settle  

### 防绕过（已加固）

- `decide` **必须**带 `actor_agent_id`，且等于会话 `owner_agent_id`
- `assert` / fulfill 绑定 **owner + amount**，确认后会话标记 **USED**（不可重放）
- 客户端 `policy_auto_allowed` **无效**；仅当身份下存在已确认的 automation-policy/preauth 且额度覆盖时才 POLICY_AUTO
- 客户端 `scene_id` 必须与意图推断场景一致，否则 400
- `require_owner_confirmation=false` **仅** `APP_ENV` ∈ development/dev/local/test 可用

演示可传 `require_owner_confirmation=false`（非开发环境会被 403）。

## API

| Method | Path |
|--------|------|
| GET | `/v1/standards/confirmation-policy` |
| GET | `/v1/standards/confirmation-policy/scenes/{scene_id}` |
| POST | `/v1/confirmations/plan` |
| POST | `/v1/confirmations/sessions` |
| GET | `/v1/confirmations/sessions/{id}` |
| POST | `/v1/confirmations/sessions/{id}/decide` |
| POST | `/v1/confirmations/assert` |
