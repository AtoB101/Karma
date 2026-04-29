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
- `CONVENTIONS.md`
- `scripts/**` (public wrappers only)

### Private domain (internal only)

- `karma-engine/internal-admin/**`
- `karma-engine/docs/**`
- `karma-engine/settlement-optimizer/examples-private/**`
- `karma-engine/PRIVATE_MIGRATION_INVENTORY.md`

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
- Changes under `karma-engine/internal-admin/**` must be reviewed as private/internal operational changes.
- Cross-boundary PRs (both public and private touched) require both reviewers.

## 4) Automation

- `scripts/visibility-guard.sh` performs boundary checks.
- `.github/workflows/visibility-guard.yml` runs these checks for pull requests.
