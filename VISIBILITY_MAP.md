# Karma Visibility Map

This document defines repository visibility boundaries and review ownership.

## 1) Visibility domains

### Public domain (safe to expose)

- `karma-core/**`
- `docs/**` (public-facing docs only)
- `openapi/**`
- `.github/workflows/**`
- `README.md`
- `SECURITY.md`
- `scripts/**` (public wrappers only)

### Private domain (not in this public repository)

Engine, internal admin, outreach, and strategy documents live in a **private** Git repository (for example Karma2). They are **not** tracked under this public monorepo path.

## 2) Boundary rules

1. Public files must not include internal path references such as:
   - `internal-admin/`
   - `docs-private/`
2. Public files must not include internal artifact names:
   - `seller-leads.csv`
   - `outreach-results.csv`
   - `PRIVATE_MIGRATION_INVENTORY`
3. Public files must not include secret-looking env keys:
   - `KARMA_API_TOKEN`
   - `USER_PRIVATE_KEY`
   - `DEPLOYER_PRIVATE_KEY`

## 3) Review policy

- Changes under `karma-core/**`, `docs/**`, `openapi/**`, and root public docs should be reviewed as public-surface changes.
- Changes that touch **private** repositories must follow the private repo’s review policy.
- Cross-boundary releases (public core + private engine) use lock/manifest + `split-release/prepare-karma2-sync-package.sh`.

## 4) Automation

- `scripts/visibility-guard.sh` performs boundary checks.
- `.github/workflows/visibility-guard.yml` runs these checks for pull requests.
