# Four Hardening Items (2026-08)

## 1. VerifierRegistry privileged writes + discovery

- `recordAttestation` / `rewardVerifier` require `onlyAuthorizedCaller` (admin or `setAuthorizedCaller`).
- Deploy script authorizes `KarmaAttestationGateway`.
- Gateway auto-calls `rewardVerifier` after a successful attestation when reward is configured.
- A2A AgentCard exposes **registry/gateway addresses** and `karma_attestation` capability only —
  not the privileged method ABIs as callable skills.

## 2. A2A Bridge EIP-712

- Domain: `KarmaA2A` v1; type: `A2ATaskOp` (aligned with on-chain EIP-712 encoding).
- All write endpoints require signed `auth` when `A2A_REQUIRE_EIP712=1` (default).
- Nonce replay protection stored alongside the task event store.

## 3. Identity unification (DID SSOT)

- Canonical projection: `identity_id` / `AgentCard.agent_id` = `did:karma:{agent_address}`.
- API: `POST /v1/identities/project-from-did`, `GET /v1/identities/{id}/agent-card-id`.
- Profile fields: `did_agent_address`, `on_chain_did`, `projection_readonly`, `projection_source`.

## 4. `_task_store` → persistence + event sourcing

- SQLite append-only `task_events` + `task_snapshots`.
- Rebuild state from events; expose `GET /a2a/task/{id}/events`.

---

## Product spine: intent → discover → interact → verify → deliver

Target user journey: assistant understands NL intent, discovers a Karma merchant/agent,
negotiates, then relies on voucher/evidence/settle for delivery guarantees.

| Step | Surface |
|------|---------|
| Intent parse | `services/intent_discovery.py`, A2A `intent_discovery.py` |
| Discover | `POST /v1/discovery/intent`, `POST /a2a/discover`, MCP `karma_discover_for_intent` |
| Launch without known seller | `POST /v1/trade/orders/launch-from-intent` |
| **Full spine (preferred)** | `POST /v1/orchestration/fulfill-intent` / MCP `karma_fulfill_intent` / A2A `POST /a2a/fulfill` |
| Negotiate | A2A task lifecycle + EIP-712 (auto when merchant has endpoint) |
| Deliver rails | real voucher accept → settlement IN_PROGRESS → optional auto receipt + settle |

`fulfill-intent` closes the previous gaps: auto-negotiate (or inline), **real** voucher+accept,
settlement lock/start, and with `auto_complete=true` evidence receipt + buyer-accept to `SETTLED`.

### Discoverability + trust ranking

- `POST /v1/agents/connect` — agent upserts into Karma directory ⇒ immediately discoverable
- Discovery ranks: skill match → then reputation / success_rate / settled_volume / dispute_rate
- Settlement success updates reputation (`record_worker_settlement_outcome`) as “好评” proxy
- `GET /v1/agents/{id}/trust` — inspect trust signals before handing work
