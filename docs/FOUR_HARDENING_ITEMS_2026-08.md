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
