# karma-openclaw — OpenClaw MCP proof plugin

Stdio MCP server that attaches verifiable execution receipts and evidence bundles to OpenClaw agent workflows. Karma acts as a proof layer for paid agent actions — it does not replace payment or tool execution, it records proof after actions happen.

**P0 proof tools:** execution receipt construction, evidence bundle submission, verification and handoff validation. High-risk settlement actions (voucher create/accept, Runtime Key mint) remain manual in the Karma Console. See [Advanced OpenClaw Workflows](../../docs/OPENCLAW_P1_DUAL_AGENT.md) and [`examples/openclaw-dual-agent/`](../../examples/openclaw-dual-agent/).

**Runtime Key access is agent-bound.** A `KRM_RT_…` key is a bearer token — whoever holds it could spend the owner's money — so Karma mints every key against a named agent, pins it to that agent's Ed25519 public key and requires the agent to sign every `/runtime/*` request with the matching private key. The private key never leaves the agent machine, so a copied key string is useless.

**Pairing activates the key by itself.** `karma_connect` generates this machine's Ed25519 key on first use and sends its public key with the pairing request, so the owner's approval *is* the activation: `karma_connect_claim` returns a key that is already live — nothing to type, no matching code. (Without a local key, or if the declared key is malformed, the older two-step path still applies: `karma_runtime_bind_key` hands the owner an 8-character `activation_code`, then `karma_runtime_await_activation`.) Keys have no fixed expiry by default; the owner revokes them in the Console. Set `KARMA_RUNTIME_KEY`, `KARMA_AGENT_ID` and `KARMA_AGENT_PRIVATE_KEY` (Ed25519, stays on this machine). See [Runtime Key 指南](../../docs/runtime-key-guide.md).

---

## Install

```bash
pip install karma-openclaw            # published on PyPI (currently 0.4.0)
# or, from a clone:
pip install ./packages/karma-openclaw
# dev mode:
pip install -e ./packages/karma-openclaw
```

See [`docs/mcp/karma-mcp-integration.md`](../../docs/mcp/karma-mcp-integration.md).

## Run (stdio MCP)

```bash
export KARMA_RUNTIME_URL=http://localhost:8000
export KARMA_API_KEY=***karma_worker-001_***
export KARMA_OPENCLAW_HANDOFF_PATH=./handoff.json

# /runtime/* tools (agent-bound key):
export KARMA_RUNTIME_KEY=KRM_RT_…
export KARMA_AGENT_ID=<the agent this key names>
export KARMA_AGENT_PRIVATE_KEY=<base64(32 bytes) or 64-char hex>

karma-openclaw-mcp
```

## MCP Proof Tools

| Tool | Purpose |
|------|---------|
| `karma_build_execution_receipt_step` | Generate a signed receipt for one tool call |
| `karma_submit_evidence_bundle` | Package receipts into a verifiable bundle |
| `karma_get_evidence_bundle` | Retrieve a previously submitted bundle |
| `karma_validate_handoff` | Verify operator handoff for high-risk actions |
| `karma_connect` | **No key yet?** Ask to be connected; returns the `user_code` and auto-opens the owner approval page (`open_approval_page=False` to disable) |
| `karma_connect_authorize` | Prepare an in-window approval: owner's wallet + limits -> sign challenge + `sign_url` |
| `karma_connect_authorize_submit` | Submit the owner's wallet signature; approves the pairing without a console session |
| `karma_connect_claim` | Collect the credentials as soon as the owner approves; writes `~/.karma/agent.env` (0600) — including the local Ed25519 seed — and returns fingerprints only. Also answers "where is this pairing now": while it is unapproved it returns status only and consumes nothing |
| `karma_connect_status` | What this machine holds: pending pairings + credential fingerprints. Local only — it never calls the backend |
| `karma_pairing_*` | Deprecated aliases of the three above (same code path, each return carries a `deprecated` note). **Removal date: 2026-12-01** (next minor release); see `docs/AGENT_PAIRING_V1.md` |
| `karma_runtime_bind_key` | Bind this agent's Ed25519 public key; returns the matching code for the owner |
| `karma_runtime_await_activation` | Wait for the owner to enter the code; then signs every request |
| `karma_runtime_binding_status` | Where this key stands (pending / active / bearer) |
| `karma_check_automation_readiness` | Check if automation policy allows this action |
| `karma_get_settlement` | (Optional) Read settlement status |

## Onboarding with no key at all

An agent that holds nothing can still get itself connected — and the credentials never
travel through the chat:

```text
karma_connect(agent_name="claw-001", requested_side="seller", requested_vertical="food")
  -> auto-opens the owner approval page in the browser
  -> user_code "QKFS-3J5Z" + verification_uri + agent_fingerprint
     # hand these to your owner: they compare agent_fingerprint with the Console card,
     # so "the request in the Console" is provably "this machine's public key"
  ... owner reviews it in Karma Console, sets the allowance, and approves — that is the delivery
karma_connect_claim()
  -> credentials written to ~/.karma/agent.env (0600); only sha256 fingerprints returned
karma_connect_status()
  -> what this machine holds; local only, no network
```

The direction is fixed: the agent produces the code, the owner types it in, approval releases
the credentials. The agent's own `pairing_code` (256-bit, returned once, stored as SHA-256) is
the only thing that redeems them — so a `user_code` on a screenshot, or a whole chat transcript,
is worth nothing. If the owner wants one more hand-to-hand confirmation they can *optionally*
issue a `handoff_code` (3 minutes, single use); then — and only then — the claim has to carry
it too. See [Agent 配对接入 v1](../../docs/AGENT_PAIRING_V1.md).

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
