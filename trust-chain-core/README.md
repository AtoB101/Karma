# Karma (formerly trust-chain-core)

Karma: Non-custodial payment protocol for AI agents

## About

AI agents need to pay each other, but existing solutions either require custody or lack enforceable settlement. Karma uses on-chain accounting + EIP-712 signatures to enable non-custodial, trust-minimized payments between any two agents.

## Website

- Portal (test): https://atob101.github.io/Trust-Chain/
- Coming soon + waitlist: https://atob101.github.io/Trust-Chain/coming-soon.html (Karma Coming Soon)

This public repository exposes the verifiable settlement protocol baseline:

- core smart contracts
- public interfaces
- basic SDK interfaces/mocks
- minimal runnable demos
- public documentation

Commercial strategy logic is intentionally excluded and belongs in the private Karma engine repository.

## Public Scope

- `contracts/`: base settlement lifecycle and protocol interfaces
- `sdk/basic/`: public SDK types/interfaces and mock adapters
- `docs/public/`: open documentation only
- `examples/`: minimal demo usage

## Quick Start

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
forge build
forge test -q
```

Frontend demo (manual):

```bash
python3 -m http.server 8787
```

Open:
`http://127.0.0.1:8787/examples/v01-metamask-settlement.html`

Frontend demo (one command):

```bash
./start-ui.sh
```

Optional:

```bash
./start-ui.sh --open
./start-ui.sh --port 8790
```

Public P0 console entry:
`http://127.0.0.1:8787/index.html`
Reset demo data quickly:
`http://127.0.0.1:8787/index.html?demoReset=1`
Export screenshot checklist:
Click `导出演示截图清单` button on `/index.html`

P0 public UI pages:

- `http://127.0.0.1:8787/buyer/dashboard/`
- `http://127.0.0.1:8787/buyer/authorize/`
- `http://127.0.0.1:8787/buyer/bills/`
- `http://127.0.0.1:8787/buyer/agent-activity/`
- `http://127.0.0.1:8787/agent/confirm-call/`
- `http://127.0.0.1:8787/seller/dashboard/`
- `http://127.0.0.1:8787/seller/create-service/`
- `http://127.0.0.1:8787/seller/revenue/`

## GitHub Pages Portal (Test URL first, custom domain later)

A Pages workflow is included at:

- `.github/workflows/pages-portal.yml`

It publishes `trust-chain-core/` as a portal site.

After enabling Pages in repository settings, the portal test URL will be:

- `https://<your-github-username>.github.io/Trust-Chain/`

For custom domain replacement later:

1. copy `trust-chain-core/CNAME.example` to `trust-chain-core/CNAME`
2. set your real domain in `CNAME`
3. configure DNS + HTTPS in GitHub Pages settings

Detailed steps:

- `docs/public/GITHUB_PAGES_PORTAL_SETUP.md`

P0 buyer/seller/agent UI demo pages:

- `http://127.0.0.1:8787/buyer/authorize/`
- `http://127.0.0.1:8787/buyer/bills/`
- `http://127.0.0.1:8787/seller/create-service/`
- `http://127.0.0.1:8787/seller/revenue/`
- `http://127.0.0.1:8787/agent/confirm-call/`

## Capability Statement (No Internal Details)

The protocol supports:

- risk checks via pluggable engine interface
- settlement optimization via pluggable optimizer interface
- enterprise controls via external enterprise modules
- data analysis via external analytics modules

Internal decision rules, scoring formulas, route strategies, optimization models, and enterprise backend logic are not in this public repository.
