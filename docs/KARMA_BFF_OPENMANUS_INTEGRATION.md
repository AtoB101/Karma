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

## 操作端（只读状态）

- **Console**（`apps/console/`）：首页 / Receiving / Payments 已嵌入 **只读** 状态块，脚本 `scripts/karma-bff-readonly.js`。在页面内联脚本中设置 `window.KARMA_BFF_PUBLIC_BASE = "https://your-bff"` 后点「同步」。
- **Agent Guard Studio**（`apps/agent-service-guard/frontend/studio/`）：总览区「OpenManus · Karma BFF 状态」面板；配置 `karma-bff-config.js` 中的 `KARMA_BFF_PUBLIC_BASE`。CSP 已允许 `127.0.0.1:8820` / `localhost:8820` / `https:` 的 `connect-src` 用于开发；生产请收紧为你的 BFF 域名。
