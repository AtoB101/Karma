# Integrations

Karma is designed to complement existing payment and agent protocols, not replace them. Here's how Karma fits into each ecosystem.

---

## x402

**What x402 does:** HTTP-native machine payments (Coinbase-originated, now foundation-governed).

**What Karma adds:** After an x402 payment succeeds, Karma generates a verifiable receipt proving what API call was made, with what inputs, and what was returned.

### Integration Pattern

```
Client pays API via x402 (402 Payment Required + USDC)
    ↓
API responds with result
    ↓
Karma hook captures: input hash, output hash, payment reference
    ↓
Execution Receipt generated with payment_ref.type = "x402"
    ↓
Bundle submitted for audit / verification
```

### Compatible Endpoints

| Karma Endpoint | x402 Context |
|---------------|-------------|
| `POST /v1/receipts` | Submit after x402 payment completes |
| `POST /v1/bundles` | Bundle receipts with payment reference |

---

## AP2 (Agent Payment Protocol)

**What AP2 does:** Authorization intent for agent payments — specifies who can pay, how much, for what.

**What Karma adds:** After AP2 authorizes a payment intent, Karma records execution evidence proving the authorized scope was respected.

### Integration Pattern

```
AP2 creates payment intent (scope: tool, amount, counterparty)
    ↓
Agent executes within authorized scope
    ↓
Karma records receipts scoped to the intent
    ↓
Evidence bundle links to AP2 intent ID
    ↓
Verification checks receipts match intent scope
```

---

## MCP (Model Context Protocol)

**What MCP does:** Standard interface for agent-tool communication (Anthropic-originated).

**What Karma adds:** Proof of tool execution — every MCP tool call can generate a signed receipt with input/output hashes and schema references.

### Integration Pattern

```
Agent calls MCP tool
    ↓
Karma MCP proof tool intercepts: tool name, args, result
    ↓
Execution Receipt generated with template = "mcp"
    ↓
Verification template includes: input_schema_hash, output_schema_hash
```

### Karma MCP Tools

| Tool | Purpose |
|------|---------|
| `karma_build_execution_receipt_step` | Generate receipt for one MCP call |
| `karma_submit_evidence_bundle` | Package and submit bundle |
| `karma_get_evidence_bundle` | Retrieve bundle for audit |

---

## OpenClaw

**What OpenClaw does:** Agent runtime and operator workflow system.

**What Karma adds:** MCP proof plugin for OpenClaw — receipts, bundles, handoff validation, automation readiness checks.

See: [`packages/karma-openclaw/README.md`](../packages/karma-openclaw/README.md)

---

## Custom Agent Frameworks

Karma's Python SDK and OpenAPI spec allow any agent framework to integrate.

### Minimal Integration (any framework)

```python
from sdk import KarmaClient

client = KarmaClient(agent_id="my-agent", runtime_url="...", api_key=***")

# After each tool call:
receipt = client.create_receipt(
    task_id=task_id,
    tool_name="my_tool",
    input_data=inputs,
    output_data=outputs,
)

# When task completes:
bundle = client.submit_evidence_bundle(task_id=task_id)

# Before settlement:
result = client.verify(task_id=task_id, bundle_id=bundle["bundle_id"])
```

### Deep Integration (hook layer)

For frameworks that support middleware/hooks, Karma provides `KarmaHookLayer` in `core/hooks/hook_layer.py` — drop-in instrumentation for automatic receipt generation on every tool call.

---

## Protocol Compatibility Matrix

| Protocol | Payment | Authorization | Execution | Proof |
|----------|:-------:|:------------:|:---------:|:-----:|
| x402 | ✅ | — | — | Karma |
| AP2 | — | ✅ | — | Karma |
| MCP | — | — | ✅ | Karma |
| OpenClaw | — | — | ✅ | Karma |

Karma fills the **proof column** that these protocols don't cover.
