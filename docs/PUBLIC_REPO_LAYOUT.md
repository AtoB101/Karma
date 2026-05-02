# Public repository layout (Karma)

This repository is **public-only**. It contains:

| Area | Purpose |
|------|---------|
| `karma-core/` | Contracts, tests, public UI examples, SDK stubs |
| `docs/` | Public documentation and security plans |
| `openapi/` | Public API contract |
| `scripts/` | Public CI helpers and guardrails |
| `split-release/` | Publishing/sync tooling (no private engine tree) |
| `split-release/sync-templates/engine-core-devops/` | **Templates only** (`.env.example.template`, `foundry.toml`) for private-repo parity when generating Karma2 sync packages |

## What is not in this repo

- **Private engine / internal ops** live in a **private** repository (e.g. Karma2 / karma-engine remote), not in this public tree.
- Do not add `karma-engine/` back to this public repository.

## Sync to private

Use `split-release/prepare-karma2-sync-package.sh` to produce a bundle for the private repo, including vendor snapshots of public contract sources.

Generated paths such as `results/` are **not committed** to this public repository (see root `.gitignore`).
