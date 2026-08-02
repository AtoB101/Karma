# Karma Core

Karma: Non-custodial settlement protocol for AI agents.

## About

AI agents need to pay each other, but existing solutions either require custody or lack enforceable settlement. Karma uses on-chain accounting + evidence hashes to enable non-custodial, trust-minimized payments between agents.

## Website / Console

- Portal (docs): GitHub Pages via `.github/workflows/pages-portal.yml`
- **Operator console**: `apps/console/` at repository root

This package exposes the verifiable settlement protocol baseline:

- core smart contracts (`contracts/core`, led by `KarmaBilateral.sol`)
- public interfaces
- minimal examples
- public documentation (`docs/public/`)

## Quick Start

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
# from repo root:
forge build
forge test -q
```

Example HTML demo (from repo root):

```bash
python3 -m http.server 8787
```

Open: `http://127.0.0.1:8787/karma-core/examples/v01-metamask-settlement.html`

## GitHub Pages Portal

Workflow: `.github/workflows/pages-portal.yml` publishes `karma-core/` docs portal.

After enabling Pages:

- `https://<your-github-username>.github.io/Karma/`

Custom domain: copy `CNAME.example` → `CNAME` and configure DNS.

## Capability Statement (No Internal Details)

The protocol supports pluggable risk / optimizer / enterprise modules via interfaces.
Internal decision rules and private engine logic are not in this public repository.
