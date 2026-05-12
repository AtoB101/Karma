# Product security & console requirements (KARMA)

This document captures **non-negotiable security properties** and **frontend prohibitions** for the KARMA trust layer and console experience. It is a **requirements / acceptance** reference for engineering; it does not replace threat modelling or third-party audits.

**Scope note:** Many items below require a **dedicated backend** and operational environment. This public repository contains contracts, static frontends, and adapter-style tooling; **full stack implementation** is tracked against services that may live in other repositories. Status columns should be updated as work lands.

---

## A. Must implement (backend / platform)

| # | Requirement | Acceptance (summary) | Public repo status |
|---|-------------|----------------------|-------------------|
| 1 | Wallet signature login | Users authenticate with wallet signatures (EIP-191 / EIP-712 as appropriate); no password-as-secret for wallet custody | **Partial:** Agent Guard Studio uses WalletConnect session + `personal_sign` challenge (see `apps/agent-service-guard/frontend/`). Full product IAM TBD in backend. |
| 2 | API key management | Issuance, rotation, revocation, scoped keys; keys stored server-side only | **Planned** — requires API service |
| 3 | Request signature verification | Server verifies signed requests / HMAC for machine clients | **Planned** |
| 4 | Replay / duplicate submission protection | Nonces or idempotency tokens; reject stale replays | **Partial:** contracts + `SettlementIdempotencyBook` (adapter); HTTP layer TBD |
| 5 | `bill_id` idempotency | Safe retries without double bill creation | **On-chain:** contract state is source of truth; HTTP idempotency TBD |
| 6 | `evidence_hash` idempotency | Safe retries without corrupting evidence pointers | **Adapter / operator:** document keys; chain rules TBD per integration |
| 7 | Dispute state lock | Mutually exclusive transitions; no double-open / inconsistent arbitration inputs | **On-chain** dispute state machine; off-chain locks TBD |
| 8 | Rate limiting | Per-IP / per-key limits at edge and app | **Partial:** client + nginx examples; app server TBD |
| 9 | Operational audit logs | Append-only operator and security logs with trace correlation | **Partial:** `operational_log.jsonl` patterns in repetition suite |
|10 | Backend environment isolation | Secrets only in server env / secret manager | **Doc:** `.gitignore`, `SECURITY.md`; enforcement in deployment |
|11 | Private API not on public Internet | Private risk APIs only on internal network + mTLS / zero trust | **Policy:** private deployment runbooks and zero-trust network controls |
|12 | Production HTTPS | TLS everywhere; HSTS where applicable | **Doc:** `docs/deployment/KARMAPAY_DOMAIN_INTEGRATION.md` |

| 13 | Sensitive keys never in frontend | No private keys, API secrets, or admin tokens in browser bundles | **Policy + review:** see section B |

---

## B. Frontend prohibitions (must not)

1. Do **not** collect or transmit **private keys** from user wallets.  
2. Do **not** collect or transmit **mnemonic phrases**.  
3. Do **not** persist wallet **secrets** in `localStorage` / `IndexedDB` / cookies (session pubkeys / addresses only, as needed).  
4. Do **not** expose **private risk reasons** or internal policy text to end users.  
5. Do **not** expose **scoring weights** or tunable thresholds in public clients.

---

## C. Related public documents

- `SECURITY.md` — reporting and sensitive-data rules  
- `docs/TESTNET_EXECUTION_CHECKLIST.md` — local testnet repetition  
- `OPEN_SOURCE_ACKNOWLEDGEMENTS.md` — upstream attribution and boundaries  

---

*Update the “Public repo status” column as capabilities ship; avoid marking items “done” without production verification.*
