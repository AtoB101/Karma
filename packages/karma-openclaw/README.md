# karma-openclaw

**Stdio MCP server** that exposes Karma **public HTTP API** tools for **[OpenClaw](https://github.com/openclaw/openclaw)**.

**P0+P1:** settlement execution + verify/delivery MCP tools; **voucher create/accept and Runtime Key mint stay manual in Console.** See `docs/OPENCLAW_P1_DUAL_AGENT.md` and `examples/openclaw-dual-agent/`.

## Install

```bash
pip install ./packages/karma-openclaw
pip install -e ./packages/karma-openclaw
```

## Run (stdio MCP)

```bash
export KARMA_RUNTIME_URL=http://localhost:8000
export KARMA_API_KEY=karma_worker-001_secret
export KARMA_OPENCLAW_HANDOFF_PATH=./handoff.json
# Optional after explicit Console approval:
# export KARMA_OPENCLAW_ALLOW_BUYER_CONFIRM=true
# export KARMA_OPENCLAW_ALLOW_BUYER_ACCEPT=true
# export KARMA_RUNTIME_KEY=KRM_RT_...
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

### P0 (settlement path; handoff required)

| Tool | Notes |
|------|--------|
| `karma_verify_voucher` | Verify only, not accept |
| `karma_settlement_*` | pending / lock / start / submit / buyer-accept (gated) |
| `karma_submit_execution_receipt` | POST /v1/receipts |
| `karma_submit_progress` | POST /v1/progress |
| `karma_create_contract` / `create_settlement` | `ALLOW_SETUP_MUTATIONS` (default off) |
| `karma_runtime_*` | Needs `KARMA_RUNTIME_KEY` |

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
