# x402 Agent Buy API — Phase 2 Example

## 1. Start mock paid API

```bash
python3 examples/x402_agent_buy_api/mock_server.py
```

## 2. Start Karma API (from repo root)

```bash
export X402_ENABLED=true
export X402_PAYMENT_BACKEND=mock
export X402_ALLOW_PRIVATE_HOSTS=true
uvicorn api.app:app --port 8000
```

## 3. Ensure a task contract exists, then:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/x402/pay-and-fetch \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "<your-task-id>",
    "agent_id": "<buyer-identity>",
    "url": "http://127.0.0.1:9402/paid",
    "max_budget_usdc": 5
  }'
```

Response includes `receipt_id` and `external_payment` (protocol `x402`).

OpenClaw: `karma_x402_fetch` MCP tool (same payload fields).
