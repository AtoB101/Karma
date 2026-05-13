# Public ↔ private sync (index)

**Start here for contract-driven upgrades:** [`SYNC_PRIVATE_RUNTIME.md`](SYNC_PRIVATE_RUNTIME.md) — when public changes OpenAPI or verify/apply-verification schemas, what private must do and what line to put in public PRs/changelogs.

**Canonical URL (stable on `main`):** https://github.com/AtoB101/Karma/blob/main/docs/SYNC_PRIVATE_RUNTIME.md  

Contract baseline (`PUBLIC_BASELINE_COMMIT`) vs documentation-only updates: see **Contract pin vs documentation canonical** in that file.

Private pointer files may optionally record a documentation-only **`main` tip** merge SHA next to that URL for cross-check; see **Optional — pointer / ledger “main tip” cross-check** at the top of the canonical file (not a fourth audit layer). Example after PR [#42](https://github.com/AtoB101/Karma/pull/42): **`49c3ace`**.

## Other references

- [`PUBLIC_PRIVATE_OPERATIONS.md`](PUBLIC_PRIVATE_OPERATIONS.md) — repo roles, release order, manifests, emergency fixes.
- [`split-release/CROSS_REPO_DEPLOYMENT_PLAYBOOK.md`](../split-release/CROSS_REPO_DEPLOYMENT_PLAYBOOK.md) — cross-repo deployment playbook.

Private baseline and upgrade steps live in **Karma2**: `private-risk-engine/docs/SYNC_PUBLIC_REPO.md` (especially §2.1).
