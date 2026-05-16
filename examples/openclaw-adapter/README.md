# OpenClaw ↔ Karma (MCP bridge)

## Quick start

```bash
pip install -e ../../packages/karma-openclaw
export KARMA_RUNTIME_URL=http://localhost:8000
export KARMA_API_KEY=your-party-api-key
karma-openclaw-mcp
```

Register **stdio** MCP in OpenClaw. Full P1 dual-agent flow (manual Console auth + automated verify/delivery): **`docs/OPENCLAW_P1_DUAL_AGENT.md`**.

## Handoff example

Copy and edit:

```bash
cp ../../schemas/openclaw-handoff-v1.example.json ./handoff.json
# Complete Console steps, then update manual_console_steps_completed + voucher_id
```

In OpenClaw, call MCP tool `karma_validate_handoff` with the file contents before `karma_submit_verification` or receipt builders.

## Two processes (buyer / seller)

| Process | `KARMA_API_KEY` | Typical MCP usage |
|---------|-----------------|-------------------|
| Buyer OpenClaw | buyer identity key | `karma_validate_handoff`, `karma_submit_verification`, checklist |
| Seller OpenClaw | seller identity key | `karma_build_execution_receipt_step`, list progress/receipts |

Authorization (voucher accept, Runtime Key) — **Karma Console only**, not MCP.
