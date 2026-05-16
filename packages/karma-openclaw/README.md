# karma-openclaw

**Stdio MCP server** that exposes Karma **public HTTP API** tools for **[OpenClaw](https://github.com/openclaw/openclaw)**.

**P1:** verify / progress / settlement reads, handoff validation, receipt builders — **authorization (voucher create/accept, Runtime Key mint) stays manual in Karma Console.** See `docs/OPENCLAW_P1_DUAL_AGENT.md`.

## Install

```bash
pip install ./packages/karma-openclaw
pip install -e ./packages/karma-openclaw
```

## Run (stdio MCP)

```bash
export KARMA_RUNTIME_URL=http://localhost:8000
export KARMA_API_KEY=karma_worker-001_secret
# Optional: allow buyer progress confirm via API after Console approval
# export KARMA_OPENCLAW_ALLOW_BUYER_CONFIRM=true
karma-openclaw-mcp
```

Register in OpenClaw’s **MCP bridge** (stdio). Tool names are prefixed with `karma_*`.

## Tools

### v0.1 (capacity + bundles)

| Tool | Karma API |
|------|-----------|
| `karma_get_capacity` | `GET /v1/capacity/{identity_id}` |
| `karma_lock_usdc` | `POST /v1/capacity/{identity_id}/lock` |
| `karma_get_evidence_bundle` | `GET /v1/bundles/{bundle_id}` |
| `karma_get_evidence_bundle_by_task` | `GET /v1/bundles/task/{task_id}` |
| `karma_submit_evidence_bundle` | `POST /v1/bundles` |

### P1 (verify / delivery; no voucher mutate)

| Tool | Notes |
|------|--------|
| `karma_manual_auth_checklist` | Console steps for buyer/seller |
| `karma_validate_handoff` | Handoff v1 JSON + optional live voucher GET |
| `karma_submit_verification` | `POST /v1/verify` |
| `karma_list_progress_for_task` | `GET /v1/progress/task/{task_id}` |
| `karma_confirm_progress` | **Off by default** — Console preferred |
| `karma_list_receipts_for_task` | `GET /v1/receipts/task/{task_id}` |
| `karma_get_settlement` | `GET /v1/settlement/{task_id}` |
| `karma_get_voucher` | Read-only |
| `karma_new_client_nonce` | For Runtime sidecar anti-replay |
| `karma_build_execution_receipt_step` | Local unsigned receipt JSON |
| `karma_build_mcp_receipt_extension` | `mcp.*` extension helper |
| `karma_voucher_eip712_notes` | Operator signing notes |

**Not exposed (Console only):** create/accept/verify voucher, Runtime Key create/revoke.

## Security

- `KARMA_API_KEY` is a **server secret** in the OpenClaw process — not end-user chat.
- Run `karma_validate_handoff` before automated verify/delivery tools.
- Production: HTTPS, strong API keys, `AUTH_ENFORCE_PROTECTED_ROUTES`.

## Tests

```bash
pip install -e "./packages/karma-openclaw[dev]"
pytest packages/karma-openclaw/tests -q
```
