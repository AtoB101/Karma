# Private alignment report — Karma2 / engine side

**Audience:** Operators and engineers working in the **private** Karma2 (or equivalent) repository.  
**Paired document:** `docs/PUBLIC_ALIGNMENT_REPORT.md`

This file **does not** contain secrets. It describes what **must** stay private and how it connects to the **public** Trusted Agent MVP.

## Why this document exists in the public repo

Integrators read the public tree first. They need a **clear boundary**: what is supported in open source vs what requires private services, keys, or deployment contracts.

---

## PRIVATE_ONLY responsibilities (Karma2 / private engine)

| Area | Owns |
|------|------|
| Risk engine | Weights, thresholds, anomaly detection, seller/buyer risk tiers |
| Dispute recommendations | Policy matrices, escalation, automated hints |
| Scoring | Reputation formulas, graph features, training data |
| Persistence | Production databases for orders, receipts, audit logs (if not redacted) |
| Secrets | RPC URLs with auth, KMS keys, WalletConnect production project IDs |
| Optional HTTP API | Full implementation of `openapi/karma-v1.yaml` routes if not shipped publicly |

Public code may define **request/response shapes** and **call sites**; private code owns **business outcomes** that depend on undisclosed rules.

---

## Lockstep with public Karma (required)

Per `docs/PUBLIC_PRIVATE_OPERATIONS.md` and `split-release/`:

1. **Pin public commit** — `CORE_VERSION.lock` (or org equivalent) references the exact `Karma` commit that ships ABIs and `openapi/karma-v1.yaml`.
2. **Deployment manifest** — Contract addresses for `NonCustodialAgentPayment` / `SettlementEngine` per chain; must match what the public settlement adapter documents.
3. **Vendor snapshots** — Use `split-release/prepare-karma2-sync-package.sh` outputs as read-only mirrors when reconciling forge builds.

Skipping lock updates causes drift between **public documentation** and **what production executes**.

---

## How private services consume public Trusted Agent artifacts

**Inputs from public / integrators:**

- Execution receipt JSON (hashes, timestamps, tool names, `schema_version`).
- Evidence bundle digest (e.g. `karma-ta:v1/sha256/...` pointer or expanded JSON in private store).
- Optional: full receipt chain stored in private object storage; public side keeps hashes only.

**Private engine may:**

- Map bundle + order context → risk score → allow/deny/hold.
- Produce **signed** verification artifacts for downstream settlement (signature keys stay private).
- Call chain write paths (relayer, custodial ops policy) **using the same** `NonCustodialAgentPayment` ABI as public.

**Private engine must not:**

- Publish undisclosed formulas into the public repo.
- Rewrite public contracts or publish “shadow” settlement contracts without aligning the lock file.

---

## Testnet and hybrid (Phase 3)

When enabling `SETTLEMENT_MODE=testnet` or `hybrid`:

- **Private** env holds `TESTNET_BUYER_PRIVATE_KEY` / `TESTNET_SELLER_PRIVATE_KEY` (or a signer service). Never commit these to the public repo.
- **Public** repo may ship **parameter builders** and **ABI fragments**; signing and broadcast typically run in **CI or private job** unless the org explicitly open-sources a signer tool.

Tx hashes and `chain_id` should be written to **private** operational databases; public demos may print them to stdout only.

---

## Phase 4 stress (public repo)

The public **`stress_trusted_agent_runtime.py`** harness is **structural only** (receipt/evidence/proofHash/settlement-plan consistency, duplicate/replay/timeout/malformed/forged **signals**). It does **not** implement private fraud scoring; production abuse detection remains in Karma2.

---

## Checklist before merging private changes that touch Trusted Agent

- [ ] Public `Karma` commit is pinned and tagged if required by release policy.
- [ ] No secrets in public PRs; `.env` patterns only via `.env.example` / `.env.testnet.example`.
- [ ] Private risk changes do not require public repo changes unless ABI/OpenAPI actually changed.
- [ ] Evidence/receipt schema version bumps are coordinated (`schema_version` fields).

---

## Contact / ownership

Define in private org handbook: **on-call**, **security contact** (`SECURITY.md` in public), and **who approves** lockfile bumps for settlement-impacting releases.
