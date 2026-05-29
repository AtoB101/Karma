# Karma Proof Primitives

Karma's core consists of three composable primitives for attaching verifiable proof to agent actions.

---

## 1. Execution Receipt

The **atomic proof unit**: one signed record per agent tool/API call.

### Schema

| Field | Description |
|-------|-------------|
| `receipt_id` | Unique identifier |
| `task_id` | Parent task |
| `agent_id` | Agent that executed |
| `step_index` | Order within task |
| `tool_name` | Tool or API invoked |
| `input_hash` | SHA-256 of serialized input |
| `output_hash` | SHA-256 of serialized output |
| `started_at` | Execution start timestamp |
| `ended_at` | Execution end timestamp |
| `duration_ms` | Wall-clock duration |
| `status` | `success`, `failure`, `timeout`, `skipped` |
| `payment_ref` | Optional x402/AP2 payment reference |
| `signature` | Optional HMAC or EIP-712 signature |

### Template Types

| Template | Use Case |
|----------|----------|
| `api` | HTTP API calls with status codes |
| `mcp` | MCP tool invocations with schema hashes |
| `agent_runtime` | Agent framework calls with model info |
| `ai_workflow` | Multi-step workflow steps |

### Receipt Chain

Receipts are linked via `parent_receipt_id` forming an immutable chain. Breaking the chain is detectable during verification.

---

## 2. Evidence Bundle

A **portable audit package** that aggregates receipts, payment references, and verification metadata.

### Contents

- Array of execution receipts (with chain intact)
- Payment references (x402 payment ID, AP2 authorization intent)
- Delivery metadata (timestamps, recipient confirmation)
- Verification hints (expected tool names, input/output schemas)
- Optional proof hash for on-chain anchoring

### Lifecycle

1. **Build**: Collect receipts as agent runs
2. **Finalize**: Seal the bundle (no more receipts accepted)
3. **Submit**: Store bundle (IPFS or API backend)
4. **Verify**: Run structural and rule-based checks
5. **Anchor**: Optional — record proof hash on-chain

---

## 3. Verification

**Structural and rule-based checks** on receipts and bundles.

### What Verification Checks

| Check | Description |
|-------|-------------|
| Receipt signature validity | Every receipt must be signed |
| Receipt chain integrity | No gaps or breaks in `parent_receipt_id` |
| Hash correctness | `input_hash` and `output_hash` match content |
| Timestamp consistency | Timestamps in order within a task |
| Tool name matching | Tool name matches task contract |
| Payment reference | Payment ref links to a valid payment |
| Evidence completeness | All receipts present, bundle sealed |

### Verification API

```
POST /v1/verify
{
  "task_id": "...",
  "bundle_id": "...",
  "checks": ["signature", "chain", "hash", "completeness"]
}
```

Returns: `decision` ∈ {`release`, `hold`, `refund`, `dispute`} + per-check results.

---

## Putting It Together

```
Agent runs tool → Receipt generated
                     ↓
           Receipt chain maintained
                     ↓
           Bundle sealed and submitted
                     ↓
           Verification checks run
                     ↓
      Decision: release / hold / dispute
```

This three-layer architecture lets Karma serve as a proof layer for any agent payment flow without replacing the payment protocol itself.

---

## See Also

- [Integrations](./INTEGRATIONS.md) — x402, AP2, MCP, OpenClaw
- [API Reference](./API_REFERENCE.md) — Full endpoint documentation
- [Roadmap](./ROADMAP.md) — Settlement, verifiers, reputation (experimental)
