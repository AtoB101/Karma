# OpenClaw handoff webhook v1 (optional, document-only)

P1 does **not** require a running webhook receiver. This contract is for a future BFF or Karma API extension so **seller OpenClaw** can react when **buyer Console** completes authorization.

## Endpoint (future)

```http
POST /v1/webhooks/openclaw-handoff
Content-Type: application/json
X-Karma-Signature: sha256=<hmac>
```

Shared secret: same pattern as `apps/karma_bff` chain webhooks (`BFF_WEBHOOK_SECRET` or dedicated `OPENCLAW_WEBHOOK_SECRET`).

## Event envelope

```json
{
  "event_version": "1",
  "event_type": "voucher.accepted",
  "emitted_at": "2026-05-16T12:00:00Z",
  "trace_id": "trace-…",
  "payload": {
    "voucher_id": "…",
    "task_id": "…",
    "buyer_identity_id": "…",
    "seller_identity_id": "…",
    "bill_credit_amount": 35.0
  }
}
```

### `event_type` values (planned)

| Type | When |
|------|------|
| `voucher.created` | Buyer created voucher (informational) |
| `voucher.accepted` | Seller accepted in Console — **safe to start seller Claw work** |
| `settlement.delivered` | Task reached `delivered` |
| `settlement.settled` | Terminal settled |

## Consumer (OpenClaw)

1. Verify HMAC.  
2. Merge into local `handoff.json` (`authorization.voucher_status`, `manual_console_steps_completed`).  
3. Call `karma_validate_handoff` before automated tools.

Until implemented, poll `karma_get_voucher` or Console sync.
