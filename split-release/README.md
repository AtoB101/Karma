# Split Release Guide: trust-chain-core + trust-chain-engine

This directory provides reproducible scripts to publish the split repositories:

- Public repo: `trust-chain-core`
- Private repo: `trust-chain-engine`

## 1) Prerequisites

- `git` installed and authenticated
- create two empty remote repositories first:
  - `trust-chain-core` (public)
  - `trust-chain-engine` (private)

## 2) Publish public core repository

```bash
./split-release/publish-core.sh \
  --remote-url <core_remote_url> \
  --branch main
```

Example:

```bash
./split-release/publish-core.sh \
  --remote-url git@github.com:your-org/trust-chain-core.git \
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
  --remote-url git@github.com:your-org/trust-chain-engine.git \
  --branch main
```

## 4) Security checklist before publishing

- ensure no private key/API key/RPC key files are present
- ensure `trust-chain-core` contains no strategy/risk-scoring internals
- ensure `trust-chain-engine` remote visibility is private

## 5) Output directories

Scripts create isolated publish directories:

- `.split-release-out/trust-chain-core-repo`
- `.split-release-out/trust-chain-engine-repo`

These are temporary local repositories used only for clean publishing.
