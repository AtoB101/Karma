# Trust-Chain MVP API Contract (v1)

Base paths:

- Preferred: `/api/v1`
- Legacy compatibility: `/api` (same behavior during migration period)

Response envelope (unified):

```json
{
  "ok": true,
  "code": "OK",
  "message": "success",
  "data": {}
}
```

---

## Health and runtime

### GET `/api/v1/health` (or `/api/health`)
### GET `/api/v1/status` (or `/api/status`)

Returns runtime status including chain capability flags.

---

## Config

### GET `/api/v1/config` (or `/api/config`)

Returns:

- `pricePerCallWei`
- `pricePerCallEth`
- `defaultSymbol`
- `endpoint` (normalized as `/api/v1/price-paid`)

---

## Dashboard

### GET `/api/v1/dashboard` (or `/api/dashboard`)

Returns:

- `summary`
- `agents`
- `bills`
- `activity`

---

## Deployment readiness

### GET `/api/v1/deploy-readiness` (or `/api/deploy-readiness`)

Returns readiness checks for API and chain capabilities.

---

## Agents

### GET `/api/v1/agents` (or `/api/agents`)
List all agent definitions.

### POST `/api/v1/agents` (or `/api/agents`)
Create a new agent.

Body (example):

```json
{
  "name": "RiskGuard",
  "description": "Token risk check",
  "serviceType": "风险检测",
  "endpoint": "https://risk.example.com/check",
  "price": 0.05,
  "token": "USDC",
  "wallet": "0x..."
}
```

### PATCH `/api/v1/agents/:id` (or `/api/agents/:id`)
Update agent fields.

### DELETE `/api/v1/agents/:id` (or `/api/agents/:id`)
Delete an agent.

---

## Bills

### GET `/api/v1/bills` (or `/api/bills`)
Optional query:

- `status` in `PendingConfirm | PendingSettle | Paid | Disputed`

### POST `/api/v1/bills/:id/confirm` (or `/api/bills/:id/confirm`)
### POST `/api/v1/bills/:id/reject` (or `/api/bills/:id/reject`)
### POST `/api/v1/bills/:id/settle` (or `/api/bills/:id/settle`)
### POST `/api/v1/bills/:id/dispute` (or `/api/bills/:id/dispute`)

Apply lifecycle transition to one bill.

### POST `/api/v1/bills/batch-settle-now` (or `/api/bills/batch-settle-now`)
Batch settle all `PendingSettle` bills with strategy `now`.

### POST `/api/v1/bills/strategy` (or `/api/bills/strategy`)
Update one bill payment strategy.

Body:

```json
{
  "billId": "BILL-001",
  "payStrategy": "now"
}
```

---

## Allowance controls

### POST `/api/v1/allowance/stop` (or `/api/allowance/stop`)
Pause further spending.

### POST `/api/v1/allowance/increase` (or `/api/allowance/increase`)

Body:

```json
{
  "amount": 10
}
```

---

## Paid settlement

### POST `/api/v1/price-paid` (or `/api/price-paid`)
### POST `/api/v1/btc-price-paid` (or `/api/btc-price-paid`)

Body:

```json
{
  "symbol": "BTCUSDT",
  "userId": "external-user"
}
```

When chain env vars are missing, returns `503` with code `CHAIN_DISABLED`.
