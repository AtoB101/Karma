> **[LEGACY CONSOLE REMOVED]** This document describes the old multi-page console
> (Receiving / Payments / Agents / Evidence / Disputes / Trade / Dashboard / MVVS /
> Verifier Explorer / OpenClaw Connect). Those pages were deleted; the public console
> is now the single-page Cyber Console at `apps/console/pages/cyber/index.html`.

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

`PLANNED` → `SNAPSHOT_RECORDED` → `LOCK_PENDING` → `LOCKED` → `EXECUTE_ALLOWED` → `EXECUTING` → `EVIDENCE_BUILT` → (`AWAIT_ONCHAIN` — manual / indexer) → `SETTLED`

Failure / abort exits (added 2026-10-01 — before that the graph was forward-only and a
broken trace had nowhere to go):

- **any non-terminal state → `FAILED`** — `POST /v1/integration/tasks/{trace_id}/fail`
- **`PLANNED` / `SNAPSHOT_RECORDED` / `LOCK_PENDING` → `CANCELLED`** — `POST /v1/integration/tasks/{trace_id}/cancel`,
  reachable only *before* funds are locked; cancelling a locked task would claim
  something the chain does not agree with.

`SETTLED` / `FAILED` / `CANCELLED` are final — no transition leaves them.

`FAILED` is an **orchestration verdict only**: it moves **no money**. Escrow still
settles exclusively through chain events and the settlement API.

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

A lock event for a trace that is already `SETTLED` / `FAILED` / `CANCELLED` is **not** silently
ignored: the response adds `"alert": true` (`{"ignored": true, "alert": true, ...}`). Funds moved
on-chain for a trace the BFF had already closed, so the two ledgers disagree and need a human.
The trace is never resurrected by a webhook.

## Terminal exits (orchestrator → BFF)

Both require the same HMAC headers and an `Idempotency-Key`, and neither moves money.

`POST /v1/integration/tasks/{trace_id}/fail`

```json
{ "reason": "tool crashed after 3 retries" }
```

`reason` is required (1–500 chars) and stored on the task row (`status_reason`), so both
`/v1/integration/tasks/{trace_id}/status` and `/public/status/{trace_id}` show why. Replaying with a
fresh idempotency key is a no-op that returns `{"already": true}`.

`POST /v1/integration/tasks/{trace_id}/cancel`

Same body. Returns `409` once funds are locked (`LOCKED` or later) or when the task is already
terminal.

## OpenManus tools

See `packages/openmanus-karma-tools/tools.json` for tool definitions to register in your OpenManus runtime.

## 操作端（只读状态）

- **Console**（`apps/console/`）：首页 / Receiving / Payments 已嵌入 **只读** 状态块，脚本 `scripts/karma-bff-readonly.js`。在页面内联脚本中设置 `window.KARMA_BFF_PUBLIC_BASE = "https://your-bff"` 后点「同步」。
- **Console / BFF：** 使用 `apps/console` 与 `apps/karma_bff`；OpenManus 通过 `packages/karma-openmanus` 调用 BFF `/v1/integration/*`。开发时 CSP/`connect-src` 需允许你的 BFF 源。
