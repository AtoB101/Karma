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
| `karma_runtime_check_voucher` | Seller verify via Runtime (not accept) |
| `karma_poll_handoff_events` | Poll API event ring when enabled |
| `karma_automation_status` | Suggested next step for buyer/seller |
| `karma_check_automation_readiness` | `GET /v1/openclaw/automation-readiness` — server gate before auto-execute |

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

**Legacy voucher routes (Console preferred):** raw `POST /v1/vouchers` create/accept — use Phase 1 payment codes below when possible.

### Phase 1 (payment codes + trade pipeline)

| Tool | Karma API |
|------|-----------|
| `karma_build_payment_code_request` | Local helper → POST body |
| `karma_create_payment_code` | `POST /v1/payment-codes` |
| `karma_get_payment_code` | `GET /v1/payment-codes/{voucher_id}` |
| `karma_accept_payment_code` / `karma_reject_payment_code` | Seller manual actions |
| `karma_launch_trade_order` | `POST /v1/trade/orders/launch` (+ `Idempotency-Key`) |
| `karma_get_trade_order` | `GET /v1/trade/orders/{order_id}` |
| `karma_list_voucher_events` | `GET /v1/vouchers/{id}/events` |
| `karma_get_handoff_draft` / `karma_confirm_handoff` | OpenClaw operator chain |
| `karma_get_automation_policy` / `karma_save_automation_policy` | Preauth setup |
| `karma_continue_after_trade_launch` | Post-launch handoff + next-step hints |

**Still Console-only:** Runtime Key mint/revoke (wallet signing).

**Live acceptance:** `docs/PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md` · `examples/phase1-live-test/`

## Security

- `KARMA_API_KEY` is a **server secret** in the OpenClaw process — not end-user chat.
- Run `karma_validate_handoff` before automated verify/delivery tools.
- Production: HTTPS, strong API keys, `AUTH_ENFORCE_PROTECTED_ROUTES`.

## Tests

```bash
pip install -e "./packages/karma-openclaw[dev]"
pytest packages/karma-openclaw/tests -q
```
