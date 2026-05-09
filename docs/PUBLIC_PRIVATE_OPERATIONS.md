# Public vs private operations (Karma + Karma2)

This document defines how to keep **clear public/private boundaries** without slowing day-to-day releases.

## Repositories

| Repository | Role |
|------------|------|
| **Karma** (public) | Protocol surface: `karma-core/` contracts, public docs, `openapi/`, CI guardrails, sync tooling under `split-release/`. |
| **Karma2** (private) | Engine, internal admin, outreach, integration, and anything that must not be public. |

Do not copy private-only trees back into the public repository. Do not put secrets in either repository; use a secret manager and CI secrets.

## Release order (default)

1. **Freeze public baseline** — merge to the agreed branch, tag if needed, note commit SHA (`CORE_COMMIT`).
2. **Update private lock + manifest** — set `CORE_VERSION.lock` and `deployment-manifest.json` to that SHA and deployed addresses.
3. **Validate** — run `verify-manifest` (and required private CI checks) before rollout.
4. **Roll out** — deploy or configure private services against the locked public baseline.

Skipping step 2 or 3 causes drift between what users see (public ABI / docs) and what production runs (private engine).

## Day-to-day development

- **Protocol / contract / public doc changes** → pull requests in **Karma**.
- **Commercial, integration, ops, internal runbooks** → pull requests in **Karma2**.
- **When both must change** → merge **Karma** first, then bump lock/manifest in **Karma2** in the same release window (or same calendar day for hotfixes).

## Keeping private engineers unblocked

- Use `split-release/prepare-karma2-sync-package.sh` to refresh **`ops/release-sync/`** in Karma2, including **vendor snapshots** (pinned public sources and engine devops templates) without cloning the whole monorepo history into the wrong place.
- Treat vendor snapshots as **read-only mirrors** of a public commit; the source of truth remains **Karma**.

## Emergency fixes

- **Contract hotfix** → fix in **Karma**, tag, update private lock/manifest, redeploy.
- **Config / routing / feature flag only** → may be done in **Karma2** alone if it does not change the on-chain surface assumed by the lock file.

If a hotfix would change ABI or addresses, the manifest and any downstream configs must be updated in the same change set.

## Checklist before any production change

- [ ] Public `Karma` commit is identified and (if applicable) tagged.
- [ ] Karma2 `CORE_VERSION.lock` matches that commit.
- [ ] Karma2 `deployment-manifest.json` matches chain, addresses, and validation flags.
- [ ] `verify-manifest` passes in Karma2 CI or locally before merge.
- [ ] No secrets committed in either repository.

## Related documents

- `docs/PUBLIC_REPO_LAYOUT.md` — what belongs in the public tree.
- `split-release/CROSS_REPO_DEPLOYMENT_PLAYBOOK.md` — cross-repo deployment steps.
- `VISIBILITY_MAP.md` — visibility rules and automation entry points.
