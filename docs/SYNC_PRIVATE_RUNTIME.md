# Syncing the private runtime when public contracts change

**Canonical (stable on `main`):**  
https://github.com/AtoB101/Karma/blob/main/docs/SYNC_PRIVATE_RUNTIME.md  

Karma2 and other private trees should link to that URL (or a pinned `PUBLIC_BASELINE_TAG`); do not fork the long-form content—use a short pointer file in private repos if needed.

**Optional — pointer / ledger “main tip” cross-check (not a fourth semantic layer):** short pointer files may append the merge SHA of the latest **documentation-only** change on public `main` that touched this canonical file, to show the pointer was refreshed against current `main`. Treat that SHA as **operational metadata** only: it does **not** change the **three-layer contract / audit model** (`33bfa57` contract pin, `3e7de43` narrative audit, `0b61d70` long-form anchor — see table below) and does **not** advance **`PUBLIC_BASELINE_COMMIT`**. Example after PR [#42](https://github.com/AtoB101/Karma/pull/42): **`49c3ace`** (private pointers may list newer doc-only tips when convenient; no obligation to chase every merge).

---

This document is the **public-repo counterpart** to the private baseline doc  
`private-risk-engine/docs/SYNC_PUBLIC_REPO.md` (Karma2 / private-risk-engine).  
It answers: **when must private teams bump their baseline**, and **where to look for the fixed upgrade steps**.

---

## When to flag private in a public PR or changelog

Add a **single explicit line** in the PR description and/or `CHANGELOG` entry when your change affects any of:

- `openapi/karma-v1.yaml` (or published OpenAPI elsewhere under agreed sync paths), **including paths private runtimes mirror** (e.g. **`POST /v1/vouchers`**, verify, settlement)
- `core/schemas.py` fields used across the **verify → apply-verification** path (`VerificationResult`, `VerificationCheck`, `EvidenceBundle`, `TaskContract`, settlement-related DTOs)
- Request/response shapes for **`POST …/v1/verify`** or **`POST …/v1/settlement/{task_id}/apply-verification`** as consumed by the private engine

**Trigger sentence (copy-paste):**

> **Private:** bump `PUBLIC_BASELINE_COMMIT` (or `PUBLIC_BASELINE_TAG`) and run `run_public_contract_sync_tests` (and `run_schema_contract_tests` if schemas changed). See `docs/SYNC_PRIVATE_RUNTIME.md`.

If the change is **internal-only** (copy, tests, unrelated modules), you do **not** need the trigger line.

---

## What private does next (fixed playbook)

Private engineers follow **§2.1「基线再升级」** in:

`private-risk-engine/docs/SYNC_PUBLIC_REPO.md`

That section defines the closed loop. After a **contract-affecting** merge on public `main` (see the trigger list above), private teams typically:

1. Set **`PUBLIC_BASELINE_COMMIT`** to that merge commit on public **`main`**, or set **`PUBLIC_BASELINE_TAG`** if public maintainers published a tag.
2. Sync the **OpenAPI** artifact the private repo uses as contract source of truth (same shapes as public `openapi/karma-v1.yaml` when applicable).
3. Run **`run_public_contract_sync_tests`**; if JSON Schemas or generated types drift, also run **`run_schema_contract_tests`** (or your repo’s equivalent).

No separate verbal agreement is required beyond this doc pair + the PR trigger line.

---

## Baseline semantics (reference)

| Identifier | Meaning |
|------------|---------|
| **`33bfa57`** (example) | Merge commit on public **`main`** that landed a given public PR (e.g. PR #36); use as **`PUBLIC_BASELINE_COMMIT`** when you mean “we are aligned with public default branch after that merge”. |
| **`a977ce5`** (example) | A specific commit **inside** that merge history (e.g. OpenAPI-only doc commit); use when you only need to pin the **OpenAPI** delta, with the merge SHA still documented for context. |
| **`3e7de43`** (example) | Public PR [#39](https://github.com/AtoB101/Karma/pull/39): narrative alignment for contract pin vs documentation canonical, plus a `VerificationResult` docstring link. Use as an **audit anchor** for “sync prose matches public `main`”; **not** a contract baseline bump by itself. |
| **`0b61d70`** (example) | Public PR [#40](https://github.com/AtoB101/Karma/pull/40): editorial pass that threaded PR #39 into **this** canonical file (contract-pin paragraph + baseline table). Private repos may cite this as a **long-form revision anchor** — a different layer from **`3e7de43`** / PR #39. **Not** a contract baseline bump. |
| **`49c3ace`** (example) | Public PR [#42](https://github.com/AtoB101/Karma/pull/42): optional **main doc tip** semantics for private pointer/ledger cross-check; index heading fix in `PUBLIC_PRIVATE_SYNC.md`. **Operational metadata** only — not a fourth layer alongside `3e7de43` / `0b61d70`, and **not** a contract baseline bump. |
| **`b5d6961`** (example) | Public PR [#44](https://github.com/AtoB101/Karma/pull/44): **OpenAPI** `CreateVoucherRequest` gained `buyer_wallet_address` / `progress_rule_spec`; runtime env for optional voucher EIP-712 enforcement. **Bump `PUBLIC_BASELINE_COMMIT`** (or re-run contract sync) when private clients or generators track voucher create payloads or OpenAPI parity. |

Private ledgers may record **`3e7de43`** (narrative / cross-repo audit) and **`0b61d70`** (canonical long-form revision) separately; neither advances **`PUBLIC_BASELINE_COMMIT`**. Optional **main tip** SHAs (e.g. **`49c3ace`**) follow the same rule; private pointers may refresh them when aligned with latest public doc merges, without updating **`SYNC_PUBLIC_REPO.md` §2.1** layering text.

Exact SHAs change over time; always take the value from **current public `main`** after merge.

---

## Contract pin vs documentation canonical

**Private `PUBLIC_BASELINE_COMMIT` / tag** records the **API and schema contract** you implement (OpenAPI, `core/schemas.py` on the verify / apply-verification path, and generated types). Advance it when those shapes **materially change**.

Updates that only adjust **this document**, `PUBLIC_PRIVATE_SYNC.md`, or other **operational prose** on public `main` refresh the **documentation canonical** at the URL in the header. They do **not** require bumping the contract baseline by themselves. On public `main`, PR [#37](https://github.com/AtoB101/Karma/pull/37) (`badf1aa`) and PR [#38](https://github.com/AtoB101/Karma/pull/38) (`cf52a40`) were documentation and canonical-URL housekeeping only. PR [#39](https://github.com/AtoB101/Karma/pull/39) (`3e7de43`) added the **contract pin vs documentation canonical** narrative, tightened the private playbook wording, and linked `VerificationResult` in `core/schemas.py`. PR [#40](https://github.com/AtoB101/Karma/pull/40) (`0b61d70`) then reflected PR #39 in this file’s history table and prose. PR [#42](https://github.com/AtoB101/Karma/pull/42) (`49c3ace`) documented optional **main doc tip** pointer cross-checks and repaired the sync index — still **not** a contract baseline bump unless OpenAPI or schema **fields** change. PR [#44](https://github.com/AtoB101/Karma/pull/44) (`b5d6961`) **did** extend **OpenAPI** voucher create (`buyer_wallet_address`, `progress_rule_spec`); treat that merge as a **contract-affecting** baseline candidate for teams that pin voucher HTTP/OpenAPI (see table row **`b5d6961`**).

Keep **`PUBLIC_BASELINE_COMMIT`** on the merge that matches the **API surface your private code actually imports** (e.g. **`33bfa57`** if you only needed verify/settlement through PR #36). If private generators or HTTP clients track **`POST /v1/vouchers`** / OpenAPI `CreateVoucherRequest`, advance the pin to **`b5d6961`** (PR [#44](https://github.com/AtoB101/Karma/pull/44)) and re-run contract sync tests.

---

## Related documents (public tree)

- **`PUBLIC_PRIVATE_SYNC.md`** — short index for public ↔ private sync entry points.
- **`PUBLIC_PRIVATE_OPERATIONS.md`** — release order, locks, and operational boundaries.
- **`split-release/CROSS_REPO_DEPLOYMENT_PLAYBOOK.md`** — cross-repo deployment steps.

Private tree (Karma2) should link to the **canonical URL** above from `SYNC_PUBLIC_REPO.md` §2.1 so both directions are one click away.
