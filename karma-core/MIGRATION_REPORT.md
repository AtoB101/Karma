# Karma migration report (public repository)

## Current layout

The **public** repository contains **`karma-core/`** (contracts, tests, public UI), **`docs/`**, **`openapi/`**, **`scripts/`**, and **`split-release/`** tooling.

See **`docs/PUBLIC_REPO_LAYOUT.md`** for the canonical public skeleton.

## Private engine

Internal operations, outreach, MVP admin servers, and strategy documents live in a **private** Git repository (for example Karma2). They are **not** committed under this public monorepo.

Templates used only for generating private sync bundles:

- `split-release/sync-templates/engine-core-devops/` (`.env.example.template`, `foundry.toml`)

## Publishing

- Public core: `split-release/publish-core.sh`
- Private engine: maintained in the private remote; use `split-release/prepare-karma2-sync-package.sh` to align private checkouts with a public commit.

## Historical note

Older revisions of this file referenced a `karma-engine/` directory inside the public tree; that layout has been **removed** to keep the public repository free of private-domain content.
