# karma-openclaw

**Stdio MCP server** that exposes a small set of **Karma public HTTP API** tools so **[OpenClaw](https://github.com/openclaw/openclaw)** (or any host with an MCP bridge) can call Karma without embedding the full SDK.

## Install

```bash
pip install ./packages/karma-openclaw
# or editable:
pip install -e ./packages/karma-openclaw
```

## Run (stdio MCP)

```bash
export KARMA_RUNTIME_URL=http://localhost:8000
export KARMA_API_KEY=karma_worker-001_secret   # optional if your API allows dev keys
karma-openclaw-mcp
# equivalent:
python -m karma_openclaw
```

Point OpenClaw’s **MCP bridge** at this command (transport **stdio**). Tool names are prefixed by the server (`karma_*`).

## Tools (v0.1)

| Tool | Karma API |
|------|-----------|
| `karma_get_capacity` | `GET /v1/capacity/{identity_id}` |
| `karma_lock_usdc` | `POST /v1/capacity/{identity_id}/lock` |
| `karma_get_evidence_bundle` | `GET /v1/bundles/{bundle_id}` |
| `karma_get_evidence_bundle_by_task` | `GET /v1/bundles/task/{task_id}` |
| `karma_submit_evidence_bundle` | `POST /v1/bundles` (body = JSON string) |

Extend `karma_openclaw/server.py` for vouchers, settlement, receipts, etc., following `openapi/karma-v1.yaml`.

## Security

- Treat `KARMA_API_KEY` as a **server secret** (OpenClaw process env), not end-user chat.
- Production: HTTPS runtime URL, strong API keys, align with `AUTH_ENFORCE_PROTECTED_ROUTES` on the Karma API.
