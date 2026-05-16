# OpenClaw handoff webhook v1

Karma API can **emit** signed webhooks when operators complete Console steps. **Seller OpenClaw** can react without polling vouchers manually.

## Configuration (Karma API)

| Env | Purpose |
|-----|---------|
| `OPENCLAW_WEBHOOK_URL` | POST target (your Claw receiver or `scripts/openclaw_webhook_receiver.py`) |
| `OPENCLAW_WEBHOOK_SECRET` | HMAC secret → `X-Karma-Signature: sha256=…` |
| `OPENCLAW_WEBHOOK_STORE_EVENTS` | `true` → also keep last events in API memory for `GET /v1/openclaw/handoff-events` |

## Outbound request

```http
POST <OPENCLAW_WEBHOOK_URL>
Content-Type: application/json
X-Karma-Signature: sha256=<hmac>
```

Local dev receiver:

```bash
export OPENCLAW_WEBHOOK_SECRET=devsecret
python3 scripts/openclaw_webhook_receiver.py --port 8765
export OPENCLAW_WEBHOOK_URL=http://127.0.0.1:8765/hook
```

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

OpenClaw MCP: `karma_poll_handoff_events` (when `OPENCLAW_WEBHOOK_STORE_EVENTS=true`) or configure outbound URL.

Runtime seller verify (not accept): `POST /runtime/check-voucher` with `verify_voucher` permission — MCP `karma_runtime_check_voucher`.
