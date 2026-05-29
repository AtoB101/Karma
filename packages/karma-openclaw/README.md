# karma-openclaw — OpenClaw MCP proof plugin

Stdio MCP server that attaches verifiable execution receipts and evidence bundles to OpenClaw agent workflows. Karma acts as a proof layer for paid agent actions — it does not replace payment or tool execution, it records proof after actions happen.

**P0 proof tools:** execution receipt construction, evidence bundle submission, verification and handoff validation. High-risk settlement actions (voucher create/accept, Runtime Key mint) remain manual in the Karma Console. See [Advanced OpenClaw Workflows](../../docs/OPENCLAW_P1_DUAL_AGENT.md) and [`examples/openclaw-dual-agent/`](../../examples/openclaw-dual-agent/).

---

## Install

```bash
pip install ./packages/karma-openclaw
# or dev mode:
pip install -e ./packages/karma-openclaw
```

## Run (stdio MCP)

```bash
export KARMA_RUNTIME_URL=http://localhost:8000
export KARMA_API_KEY=***karma_worker-001_***
export KARMA_OPENCLAW_HANDOFF_PATH=./handoff.json

karma-openclaw-mcp
```

## MCP Proof Tools

| Tool | Purpose |
|------|---------|
| `karma_build_execution_receipt_step` | Generate a signed receipt for one tool call |
| `karma_submit_evidence_bundle` | Package receipts into a verifiable bundle |
| `karma_get_evidence_bundle` | Retrieve a previously submitted bundle |
| `karma_validate_handoff` | Verify operator handoff for high-risk actions |
| `karma_check_automation_readiness` | Check if automation policy allows this action |
| `karma_get_settlement` | (Optional) Read settlement status |

## Quick Demo

```bash
pip install -e ".[dev]"
uvicorn api.app:app --reload &
export KARMA_RUNTIME_URL=http://127.0.0.1:8000
export KARMA_API_KEY=***

karma-openclaw-mcp
```

Then connect OpenClaw to the MCP server and call `karma_build_execution_receipt_step`.

---

## License

AGPL-3.0-only — see [LICENSE](../../LICENSE).
