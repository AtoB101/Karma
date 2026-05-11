# Karma BFF ↔ OpenManus — integration spec

## Auth (integration caller = OpenManus server or your orchestrator)

Every `POST`/`PATCH` under `/v1/integration/` requires:

| Header | Value |
|--------|--------|
| `X-Karma-Timestamp` | Unix seconds (string) |
| `X-Karma-Signature` | Hex-encoded **HMAC-SHA256** over `\n`.join([timestamp, raw_body_utf8]) using `BFF_INTEGRATION_SECRET` |

Clock skew: **±300s** rejected otherwise.

## Idempotency

Send `Idempotency-Key: <unique per logical operation>` on mutating calls; same key returns **same JSON** within 24h.

## Closed-loop states (server-side)

`PLANNED` → `SNAPSHOT_RECORDED` → `LOCK_PENDING` → `LOCKED` → `EXECUTE_ALLOWED` → `EVIDENCE_BUILT` → (`AWAIT_ONCHAIN` — manual / indexer) → `SETTLED` (optional stub)

- **OpenManus may only start heavy execution** after BFF state is **`EXECUTE_ALLOWED`** (set by **chain webhook** or **dev simulate**).
- **Money moves on-chain only** via user wallets or your indexer; BFF never asks for seed phrases.

## Webhook (indexer → BFF)

`POST /v1/webhooks/chain` with same HMAC headers, JSON body:

```json
{
  "trace_id": "trace-...",
  "event": "LOCK_CONFIRMED",
  "tx_hash": "0x...",
  "bill_id": 123,
  "chain_id": 11155111
}
```

Supported `event` values: `LOCK_CONFIRMED`, `BILL_CREATED` (both advance toward `EXECUTE_ALLOWED` in dev profile).

## OpenManus tools

See `packages/openmanus-karma-tools/tools.json` for tool definitions to register in your OpenManus runtime.
