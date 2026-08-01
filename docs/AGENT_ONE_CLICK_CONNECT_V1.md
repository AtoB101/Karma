# Agent One-Click Connect V1

Vertical agents（酒店 / 饭店 / 电商 / 客服 / 企业…）用一次 HTTP 调用接入 Karma：目录落库 + 边界骨架 + P1 状态 + 引导 API Key。

## Endpoint

```http
POST /v1/agents/one-click-connect
Content-Type: application/json
```

List aliases:

```http
GET /v1/agents/one-click-verticals
```

## Minimal request

**Seller (饭店 Agent)**

```json
{
  "side": "seller",
  "vertical": "food",
  "display_name": "NoonBowl Merchant Agent"
}
```

**Buyer**

```json
{
  "side": "buyer",
  "vertical": "user",
  "display_name": "Alice Buyer Agent"
}
```

**Enterprise**

```json
{
  "side": "seller",
  "vertical": "enterprise",
  "self_description": "B2B procurement and invoice settlement"
}
```

## Vertical aliases

| vertical | industry / scene | profile |
|----------|------------------|---------|
| `hotel` | `hotel_booking` | merchant |
| `food` / `restaurant` | `food_delivery` | merchant |
| `ecommerce` / `retail` | `logistics_delivery` | merchant |
| `customer_service` / `cs` | `api_tool_call` | merchant |
| `enterprise` / `b2b` | `b2b_procurement` | enterprise |
| `ride` | `ride_hailing` | merchant |
| `flight` | `flight_booking` | merchant |
| `api` / `data_api` | `data_api_billing` | merchant |
| raw catalog `industry_id` | same | merchant |

`side=buyer` always maps to profile `user`.

## Response (shape)

- `agent` — directory identity  
- `scene_ids` / `boundary` / `p1_ready` / `p1_status`  
- `credentials.api_key` — `karma_{agent_id}_{secret}`（**仅返回一次明文**）  
- `env_snippet` — 可直接导出的环境变量  
- `next_steps` — 发现 / fulfill / runtime key 指引  

## Auth

- Minted bootstrap keys are verified by `api/middleware/auth.py` via hashed store (`.karma_data/agent_api_keys.json`).
- When `AUTH_ENFORCE_PROTECTED_ROUTES=true`, callers still need a prior bootstrap/admin key to hit the endpoint; after connect, the minted key authenticates that agent.
- Production still requires owner PoP + signed responsibility ack + real `service_specs` (same P1 gates as `connect-from-template`).

## curl

```bash
curl -sS -X POST "$KARMA_RUNTIME_URL/v1/agents/one-click-connect" \
  -H 'Content-Type: application/json' \
  -d '{"side":"seller","vertical":"hotel","display_name":"Harbor Hotel Agent"}' | jq .
```

## Related

- `POST /v1/agents/connect-from-template` — full template path  
- `docs/AGENT_ONBOARDING_TEMPLATE_V1.md` — industry catalog  
- `docs/AGENT_P1_ONBOARDING_V1.md` — P1 readiness / anti-forgery  
