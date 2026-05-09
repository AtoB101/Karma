# Split release and cross-repo sync (Karma public)

This directory contains tooling for the **public** Karma repository (`karma-core/`, `docs/`, `openapi/`, etc.).

The **private engine** (internal admin, outreach, strategy) is **not** stored in this public tree. It lives in a **private** repository (for example [Karma2](https://github.com/AtoB101/Karma2)).

## Cross-repo deployment

- Playbook: `split-release/CROSS_REPO_DEPLOYMENT_PLAYBOOK.md`
- Core version lock (public template): `split-release/templates/core-version.lock.example`
- Deployment manifest (public template): `split-release/templates/deployment-manifest.example.json`
- Manifest validator: `split-release/verify-cross-repo-manifest.sh`

## Publish public core only

```bash
./split-release/publish-core.sh \
  --remote-url <core_remote_url> \
  --branch main
```

## Private engine

`split-release/publish-engine.sh` is retained as a stub: the public repo no longer contains `karma-engine/`.  
Use your private repo’s normal git workflow; sync public baselines into it with:

```bash
./split-release/prepare-karma2-sync-package.sh --out-dir results/karma2-sync-package
```

## Engine devops templates (for sync bundles only)

- `split-release/sync-templates/engine-core-devops/` — `.env.example.template` and `foundry.toml` copies used by `prepare-karma2-sync-package.sh` (not a full engine tree).

## Karma2 alignment templates

- `split-release/templates/karma2/*` — lock, manifest, verify script, lockstep CI workflow.

## Generate a Karma2 sync package

```bash
./scripts/private-repo-sync.sh --private-repo-url https://github.com/AtoB101/Karma2.git
```

```bash
./split-release/prepare-karma2-sync-package.sh --out-dir results/karma2-sync-package
```

The bundle includes **read-only vendor snapshots** under `vendor/karma-public-sync/` (public `foundry.toml` template path + `NonCustodialAgentPayment.sol`).
