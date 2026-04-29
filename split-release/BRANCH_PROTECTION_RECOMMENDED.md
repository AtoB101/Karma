# Branch Protection Recommended Baseline

This document provides recommended GitHub branch protection settings for:

- `karma-core` (public repository)
- `karma-engine` (private repository)

## 1) karma-core (public)

Target protected branches:

- `main`
- release branches (if used): `release/*`

Recommended settings:

1. Require a pull request before merging: **ON**
2. Require approvals: **2**
3. Dismiss stale pull request approvals when new commits are pushed: **ON**
4. Require review from code owners: **ON**
5. Require status checks to pass before merging: **ON**
6. Required checks:
   - `boundary-guard`
   - `foundry`
   - `sdk-demo`
   - `security-lite`
7. Require conversation resolution before merging: **ON**
8. Require signed commits: **ON**
9. Require linear history: **ON**
10. Restrict who can push to matching branches: **ON** (maintainers only)
11. Do not allow force pushes: **ON**
12. Do not allow deletions: **ON**

Optional (recommended):

- Require merge queue: **ON** (if your org enables merge queue)
- Restrict merge method to squash merge for cleaner audit history

## 2) karma-engine (private)

Target protected branches:

- `main`
- protected internal branches: `prod/*`, `hotfix/*`

Recommended settings:

1. Require a pull request before merging: **ON**
2. Require approvals: **2** (or **3** for `prod/*`)
3. Dismiss stale pull request approvals when new commits are pushed: **ON**
4. Require review from code owners: **ON**
5. Require status checks to pass before merging: **ON**
6. Required checks:
   - `private-boundary-guard`
   - `python-validation`
   - `node-validation`
   - `security-secrets`
   - `interface-compatibility`
7. Require conversation resolution before merging: **ON**
8. Require signed commits: **ON**
9. Require linear history: **ON**
10. Restrict who can push to matching branches: **ON** (core maintainers only)
11. Do not allow force pushes: **ON**
12. Do not allow deletions: **ON**

Private-repo additional controls:

- Enable secret scanning and push protection
- Enable Dependabot alerts (private ecosystem deps)
- Require CODEOWNERS approval for:
  - `risk-engine/**`
  - `routing-engine/**`
  - `settlement-optimizer/**`
  - `pricing-strategy/**`
  - `internal-admin/**`

## 3) Minimal CODEOWNERS recommendation

For `karma-core`:

```text
* @core-maintainers
contracts/** @core-protocol-team
sdk/** @sdk-team
docs/** @docs-team
```

For `karma-engine`:

```text
* @engine-maintainers
risk-engine/** @risk-team
routing-engine/** @routing-team
settlement-optimizer/** @optimizer-team
pricing-strategy/** @pricing-team
internal-admin/** @platform-security-team
```

## 4) Rollout order

1. Enable required status checks in "monitor" mode for 1-2 cycles.
2. Verify no flaky jobs.
3. Switch to strict required checks.
4. Restrict push permissions.
5. Audit exceptions monthly.
