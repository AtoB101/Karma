# Developer execution plan — public KARMA repository

Single source for **execution order**, **priority tiers**, and **release acceptance** language used across product and engineering.

---

## 1. Execution order (recommended)

Complete in this sequence unless a dependency blocks you:

1. Split marketing / brochure HTML into `apps/website` (static site).  
2. Wire **Open Console** CTA → `/console` route (hosting / reverse-proxy concern).  
3. Wire **Deploy Locally** CTA → `/developers` route.  
4. Create `apps/console` shell pages (static or SPA — align with hosting).  
5. Implement **wallet signature login** on console (reuse patterns from Agent Guard where possible).  
6. Implement **Receiving / Payments** core console views (read-only chain state first, then actions).  
7. Create **public API routes** (contract-first: extend `openapi/karma-v1.yaml` before code).  
8. Freeze **Evidence Bundle** public schema (align with `trusted_agent_runtime` + on-chain `proofHash` semantics).  
9. Publish **SDK** (versioned package; narrow surface).  
10. Publish **CLI** (`karma-agent` or equivalent; align with README Quick Start when ready).  
11. Ship **Docker** local deployment template (`docker compose` + documented env).  
12. Ship **OpenManus adapter** example (thin adapter only — no private rules).  
13. Add **private risk engine mock** for internal integration tests only (no secrets in git).  
14. Connect public API → private API **only server-side** (BFF / gateway).  
15. **Testnet** end-to-end validation (`docs/TESTNET_EXECUTION_CHECKLIST.md`).  
16. Complete **README + docs** pass for integrators.  
17. **Never** commit private scoring, fraud rules, dispute weights, or proprietary datasets to the public repo.

---

## 2. Priority tiers

### P0 — must ship first

1. Website button wiring (Console, Deploy Locally)  
2. Console base pages  
3. Wallet connect / signature login  
4. Agent registration (public-safe fields only)  
5. Bill creation (against existing contracts)  
6. Evidence bundle submission (public schema)  
7. Settlement status reads  
8. Deploy Locally / developers page  
9. CLI `init` / `connect` / `register` (when CLI package exists)  
10. Private risk-check **mock** API for staging (no production secrets)

### P1 — next

1. Dispute flow UX (status + evidence; decisions from private service)  
2. Reputation display (aggregates only — no private weights)  
3. OpenManus adapter (sample)  
4. Docker local deployment polish  
5. Full SDK coverage  
6. Contract event indexing / listener

### P2 — later

1. Automated settlement helpers  
2. Automated slash flows (policy-bound)  
3. Advanced risk (private)  
4. Enterprise onboarding  
5. Multi-chain  
6. Third-party agent marketplaces

---

## 3. Final acceptance (one-liner standard)

- **Website** establishes trust.  
- **Console** completes protected operations.  
- **SDK / CLI** onboards developers.  
- **Public repo** holds protocol standards and safe adapters.  
- **Private repo** holds real risk, scoring, and arbitration core.

### Measurable gates (public side)

1. End user can reach Console from the website.  
2. User can connect a wallet.  
3. User can see **Receiving** and **Payments** areas.  
4. Developer can follow **local deploy** docs from the site.  
5. Developer can register an Agent (public-safe).  
6. Agent flow can create a **bill** (on-chain).  
7. Agent can submit **evidence** artifacts (public schema).  
8. System can query **settlement** status.  
9. Dispute can enter **review** state (without leaking private reasons).  
10. Private risk logic stays off the public surface.  
11. Official or self-hosted console still talks to the **same trust layer contracts** and public API contracts.

---

*Maintainers: edit priorities here instead of duplicating long lists across issues.*
