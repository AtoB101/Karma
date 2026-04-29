# Karma Repository Conventions

This file freezes naming, API, and structure conventions for launch-phase stability.

## 1) Project naming

- Product/repo-facing name: `Karma`
- Do not introduce new `TrustChain` / `Trust-Chain` naming in active docs, scripts, UI, or API specs.
- Historical references may remain only when needed for immutable protocol compatibility or external citations.

## 2) API path conventions

- Canonical API namespace: `/api/v1/*`
- OpenAPI contract file: `openapi/karma-v1.yaml`
- Frontend callers should use `/api/v1/*` as default.
- Backends may keep compatibility aliases (`/v1/*` or legacy paths) but must preserve canonical `/api/v1/*`.

## 3) Evidence and contract artifacts

- Evidence sample path: `docs/samples/karma-evidence-sample-v1.json`
- Output artifacts must preserve contract fields:
  - `schemaVersion`
  - `generatedAt`
  - `source`
  - `traceId`

## 4) Scripts and execution entrypoints

- Root CI entry wrappers are under `scripts/`.
- Private engine operational scripts are under:
  - `trust-chain-engine/internal-admin/scripts-private/`
- Internal compatibility shim:
  - `trust-chain-engine/internal-admin/scripts -> scripts-private`

## 5) Structure discipline

- Keep runtime-relevant assets in active trees.
- Do not reintroduce split/migration-only helper directories into mainline unless explicitly required.
- Prefer additive docs under current domains (`docs/`, `trust-chain-core/docs/public/`, `trust-chain-engine/docs/`, `trust-chain-engine/internal-admin/docs-private/`).

## 6) Pre-merge gates (required)

Before merging to `main`, ensure all required checks are green:

- `quick-check`
- `full-check`
- `security-gates`

And run release pipeline locally when possible:

- `./trust-chain-engine/internal-admin/scripts-private/release-readiness.sh`
