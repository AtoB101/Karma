# Syncing the private runtime when public contracts change

**Canonical (stable on `main`):**  
https://github.com/AtoB101/Karma/blob/main/docs/SYNC_PRIVATE_RUNTIME.md  

Karma2 and other private trees should link to that URL (or a pinned `PUBLIC_BASELINE_TAG`); do not fork the long-form content—use a short pointer file in private repos if needed.

---

This document is the **public-repo counterpart** to the private baseline doc  
`private-risk-engine/docs/SYNC_PUBLIC_REPO.md` (Karma2 / private-risk-engine).  
It answers: **when must private teams bump their baseline**, and **where to look for the fixed upgrade steps**.

---

## When to flag private in a public PR or changelog

Add a **single explicit line** in the PR description and/or `CHANGELOG` entry when your change affects any of:

- `openapi/karma-v1.yaml` (or published OpenAPI elsewhere under agreed sync paths)
- `core/schemas.py` fields used across the **verify → apply-verification** path (`VerificationResult`, `VerificationCheck`, `EvidenceBundle`, `TaskContract`, settlement-related DTOs)
- Request/response shapes for **`POST …/v1/verify`** or **`POST …/v1/settlement/{task_id}/apply-verification`** as consumed by the private engine

**Trigger sentence (copy-paste):**

> **Private:** bump `PUBLIC_BASELINE_COMMIT` (or `PUBLIC_BASELINE_TAG`) and run `run_public_contract_sync_tests` (and `run_schema_contract_tests` if schemas changed). See `docs/SYNC_PRIVATE_RUNTIME.md`.

If the change is **internal-only** (copy, tests, unrelated modules), you do **not** need the trigger line.

---

## What private does next (fixed playbook)

Private engineers follow **§2.1「基线再升级」** in:

`private-risk-engine/docs/SYNC_PUBLIC_REPO.md`

That section defines the closed loop, typically:

1. Set **`PUBLIC_BASELINE_COMMIT`** to the new merge commit on public **`main`**, or set **`PUBLIC_BASELINE_TAG`** if public maintainers published a tag.
2. Sync the **OpenAPI** artifact the private repo uses as contract source of truth (same shapes as public `openapi/karma-v1.yaml` when applicable).
3. Run **`run_public_contract_sync_tests`**; if JSON Schemas or generated types drift, also run **`run_schema_contract_tests`** (or your repo’s equivalent).

No separate verbal agreement is required beyond this doc pair + the PR trigger line.

---

## Baseline semantics (reference)

| Identifier | Meaning |
|------------|---------|
| **`33bfa57`** (example) | Merge commit on public **`main`** that landed a given public PR (e.g. PR #36); use as **`PUBLIC_BASELINE_COMMIT`** when you mean “we are aligned with public default branch after that merge”. |
| **`a977ce5`** (example) | A specific commit **inside** that merge history (e.g. OpenAPI-only doc commit); use when you only need to pin the **OpenAPI** delta, with the merge SHA still documented for context. |

Exact SHAs change over time; always take the value from **current public `main`** after merge.

---

## Related documents (public tree)

- **`PUBLIC_PRIVATE_SYNC.md`** — short index for public ↔ private sync entry points.
- **`PUBLIC_PRIVATE_OPERATIONS.md`** — release order, locks, and operational boundaries.
- **`split-release/CROSS_REPO_DEPLOYMENT_PLAYBOOK.md`** — cross-repo deployment steps.

Private tree (Karma2) should link to the **canonical URL** above from `SYNC_PUBLIC_REPO.md` §2.1 so both directions are one click away.
