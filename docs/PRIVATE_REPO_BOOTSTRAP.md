# Private Repository Bootstrap

This document explains how to bootstrap a **private child repository** and
move sensitive internal assets out of the public codebase.

## 1) Create private child repository

Example:

- GitHub repo name: `Karma-Internal`
- Visibility: **Private**
- Owners: minimal set (security + operations)

## 2) Generate bootstrap package from public repo

From this repository root:

```bash
make private-repo-bootstrap
```

This creates:

- `results/private-repo-bootstrap/README.md`
- `results/private-repo-bootstrap/docs/private/.gitkeep`
- `results/private-repo-bootstrap/scripts/private/.gitkeep`
- `results/private-repo-bootstrap/examples/private/.gitkeep`
- `results/private-repo-bootstrap/outreach/.gitkeep`
- `results/private-repo-bootstrap/SECURITY_PRIVATE.md`

## 3) Seed child private repository

In your private repository:

```bash
cp -R /path/to/public-repo/results/private-repo-bootstrap/* .
git add .
git commit -m "chore: bootstrap private repo structure"
git push
```

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
- Use `make security-baseline-guard` in PR validation.
