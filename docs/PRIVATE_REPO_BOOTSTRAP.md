# Private Repository Bootstrap

This document explains how to bootstrap a **private child repository** and
move sensitive internal assets out of the public codebase.

## 1) Create private child repository

Example:

- GitHub repo name: `Karma2` (or `Karma-Internal`)
- Visibility: **Private**
- Owners: minimal set (security + operations)

## 2) Generate bootstrap package from public repo

From this repository root:

```bash
./scripts/private-repo-sync.sh --private-repo-url https://github.com/AtoB101/Karma2.git
```

This writes under **`results/private-repo-sync/`** (gitignored by default), for example:

- `manifest.txt`
- `README.md`
- `bootstrap-private-repo.sh`
- `karma2-template/` (alignment templates when present)

For full cross-repo sync (interfaces, OpenAPI, vendor snapshots), use:

```bash
./split-release/prepare-karma2-sync-package.sh --out-dir results/karma2-sync-package
```

## 3) Seed child private repository

Copy the generated output into your private repository, then commit and push.

## 4) Move sensitive assets into private repo

Move categories:

- investor and fundraising materials
- tokenomics parameter worksheets
- partner integration runbooks and scripts
- outreach lead files and internal CRM exports
- incident response playbooks and unreleased audit appendices

## 5) Public repo policy after split

- Keep only auditable source code and public-safe docs.
- Keep all secrets in secure secret managers (never in git).
- Run `./scripts/security-baseline-guard.sh` in PR validation.
