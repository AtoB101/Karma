# Karma

**Proof receipts for paid agent actions.**

Karma is a lightweight proof layer for AI agents, MCP tools, and paid API calls.
It attaches verifiable receipts and evidence bundles to x402, AP2, and MCP transactions,
so developers can prove what was authorized, executed, and delivered.

> Karma does not replace payment protocols. It complements them.

| Protocol | What it does | What Karma adds |
|----------|-------------|-----------------|
| x402 | HTTP-native machine payments | proof of paid API/tool execution |
| AP2 | agent payment authorization | post-authorization execution evidence |
| MCP | agent tool interface | traceable tool receipts |
| OpenClaw | agent runtime / operator workflow | MCP proof plugin and handoff checks |

---

## Why Karma

Agent payments are getting easier. **Proof is still messy.**

When an agent pays for a tool, API, model, or service, teams still need to answer:

- What exactly was authorized?
- Which tool or API was called?
- What inputs and outputs were involved?
- Was the result actually delivered?
- Can the transaction be audited later?
- Can disputes be resolved with evidence?

Karma provides a small, portable proof layer for these questions.

---

## What Karma Adds

Three primitives:

### Execution Receipt

A signed, hashable record of one agent/tool/API action:

- agent id · tool name · input hash · output hash · timestamp · status · payment reference

### Evidence Bundle

A portable package of receipts, payment refs, delivery metadata, and verification hints. Use it for audit trails, buyer/seller review, dispute support, and settlement workflows.

### Verification

A simple API and MCP interface to check whether receipts and bundles match expected task rules.

---

## Quick Start

```bash
git clone https://github.com/AtoB101/Karma.git
cd Karma

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp deploy/.env.local-openclaw.example .env

uvicorn api.app:app --reload
```

Health check: `curl http://127.0.0.1:8000/health`

API docs: `http://127.0.0.1:8000/docs`

> See **[Getting Started](./docs/GETTING_STARTED.md)** for the 10-minute receipt + bundle + verify walkthrough.

---

## Proof Demo (30 seconds)

```python
from karma import KarmaClient

karma = KarmaClient(
    runtime_url="http://localhost:8000",
    api_key=***karma_***_***",
)

with karma.trace(
    task_id="task_123",
    payment_ref={"type": "x402", "id": "pay_abc"},
    tool_name="mcp.search",
) as trace:
    result = search_tool("latest pricing data")
    trace.record_output(result)

bundle = karma.create_evidence_bundle(task_id="task_123")
print(bundle["bundle_id"])
```

---

## OpenClaw MCP Proof Plugin

Karma includes a stdio MCP server for OpenClaw-compatible runtimes:

```bash
pip install -e ./packages/karma-openclaw

export KARMA_RUNTIME_URL=http://127.0.0.1:8000
export KARMA_API_KEY=***

karma-openclaw-mcp
```

Example MCP proof tools: `karma_build_execution_receipt_step`, `karma_submit_evidence_bundle`, `karma_get_evidence_bundle`, `karma_validate_handoff`.

---

## Core API Surface

**Proof APIs:**

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/receipts` | Submit execution receipt |
| `GET /v1/receipts/task/{task_id}` | List receipts for a task |
| `POST /v1/bundles` | Create evidence bundle |
| `GET /v1/bundles/{bundle_id}` | Retrieve bundle |
| `POST /v1/verify` | Verify receipts and bundles |

**Workflow APIs (optional):**

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/settlement/{task_id}` | Settlement status |
| `POST /v1/settlement/{task_id}/submit` | Submit for settlement |
| `GET /v1/openclaw/handoff-draft` | Operator handoff draft |
| `POST /v1/openclaw/handoff-confirm` | Confirm handoff |

Full spec: [`openapi/karma-v1.yaml`](./openapi/karma-v1.yaml)

---

## Architecture

```
Agent / MCP Tool / Paid API
         ↓
   Execution Receipt
         ↓
   Evidence Bundle
         ↓
   Verification API
         ↓
Optional: settlement / dispute / reputation workflows
```

---

## Advanced Modules

Karma also includes experimental infrastructure for deeper agent-commerce workflows:

- **Settlement workflows** — voucher, payment-code, capacity, trade order pipeline
- **Decentralized verifier experiments** — N-of-M attestation, challenge windows
- **Smart contracts** — non-custodial payment, attestation gateway, circuit breaker
- **Reputation signals** — agent scores from on-chain events
- **Dispute support** — arbitration rules, evidence comparison
- **x402 integrations** — hybrid settlement, API payment references
- **AP2-style authorization** — payment intents, mandate mapping

These modules are available for teams building deeper workflows, but the core developer path starts with receipts and evidence bundles.

> See **[Roadmap](./docs/ROADMAP.md)** and **[Advanced Docs](./docs/)** for details.

---

## Project Layout

```
api/                          FastAPI proof and workflow APIs
services/                     receipt, bundle, settlement, verification logic
sdk/                          Python SDK
packages/sdk/                 TypeScript SDK
packages/karma-openclaw/      OpenClaw MCP proof plugin
packages/karma-openmanus/     OpenManus HMAC proof client
openapi/                      API specs
apps/console/                 operator console
karma-core/contracts/         optional smart contracts
docs/                         integration and advanced docs
```

---

## Status

Karma is early-stage infrastructure for builders experimenting with paid agent actions, MCP tools, and verifiable execution workflows. APIs may evolve while the proof primitives stabilize.

---

## License

AGPL-3.0-only, with commercial licensing available.
See [LICENSE](./LICENSE) and [docs/LICENSING.md](./docs/LICENSING.md).
