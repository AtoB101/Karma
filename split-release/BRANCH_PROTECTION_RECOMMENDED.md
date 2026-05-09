# Branch Protection Recommended Baseline

This document provides recommended GitHub branch protection settings for:

- This **public** repository (Karma — `karma-core/` surface)
- Your **private** engine repository (e.g. Karma2; not stored here)

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

## 2) Private engine repository (e.g. Karma2)

Apply the same discipline as §1 on the **private** remote: required PRs, approvals,
status checks (including lockstep manifest verification if configured), signed commits,
and secret scanning. Exact job names depend on your private CI configuration.

## 3) Minimal CODEOWNERS recommendation

For `karma-core`:

```text
* @core-maintainers
contracts/** @core-protocol-team
sdk/** @sdk-team
docs/** @docs-team
```

For the private engine repository, define CODEOWNERS there (not in this public repo).

## 4) Rollout order

1. Enable required status checks in "monitor" mode for 1-2 cycles.
2. Verify no flaky jobs.
3. Switch to strict required checks.
4. Restrict push permissions.
5. Audit exceptions monthly.
