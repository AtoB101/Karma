# Split Release Guide: karma-core + karma-engine

This directory provides reproducible scripts to publish the split repositories:

- Public repo: `karma-core`
- Private repo: `karma-engine`

## Cross-repo deployment operations

For production deployment orchestration across public/private repositories:

- Playbook: `split-release/CROSS_REPO_DEPLOYMENT_PLAYBOOK.md`
- Core version lock template: `split-release/templates/core-version.lock.example`
- Deployment manifest template: `split-release/templates/deployment-manifest.example.json`
- Manifest validator: `split-release/verify-cross-repo-manifest.sh`

## 1) Prerequisites

- `git` installed and authenticated
- create two empty remote repositories first:
  - `karma-core` (public)
  - `karma-engine` (private)

## 2) Publish public core repository

```bash
./split-release/publish-core.sh \
  --remote-url <core_remote_url> \
  --branch main
```

Example:

```bash
./split-release/publish-core.sh \
  --remote-url git@github.com:your-org/karma-core.git \
  --branch main
```

## 3) Publish private engine repository

```bash
./split-release/publish-engine.sh \
  --remote-url <engine_remote_url> \
  --branch main
```

Example:

```bash
./split-release/publish-engine.sh \
  --remote-url git@github.com:your-org/karma-engine.git \
  --branch main
```

## 4) Security checklist before publishing

- ensure no private key/API key/RPC key files are present
- ensure `karma-core` contains no strategy/risk-scoring internals
- ensure `karma-engine` remote visibility is private

## 5) Output directories

Scripts create isolated publish directories:

- `.split-release-out/karma-core-repo`
- `.split-release-out/karma-engine-repo`

These are temporary local repositories used only for clean publishing.
