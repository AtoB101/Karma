# KARMA — open trust and settlement for AI Agents

**KARMA** is an open trust and settlement layer for AI Agents.

It allows developers, businesses and autonomous services to connect Agents to:

- non-custodial settlement  
- verifiable execution records  
- evidence-based dispute resolution  
- portable Agent reputation  
- open local deployment  

**KARMA is not an Agent runtime.**  
**KARMA** connects Agent runtimes to trust, settlement and reputation infrastructure.

### Supported integrations (ecosystem)

- OpenManus  
- OpenClaw  
- Hermes  
- Custom Agents  
- API Services  
- Data Providers  

Integration depth varies by component: public adapters and contracts live in this repository; some connectors are documented or shipped as examples elsewhere.

---

## Quick Start

### Target distribution (product packaging)

Some releases may ship under a **Trust-Chain** style monorepo or installer. The **authoritative public protocol source** for this line of work is maintained here:

```bash
git clone https://github.com/AtoB101/Karma.git
cd Karma
```

Optional testnet / hybrid tooling (Python `web3`):

```bash
cp .env.testnet.example .env.testnet.local   # edit locally; never commit secrets
pip install -r requirements-testnet.txt
# See docs/TESTNET_EXECUTION_CHECKLIST.md and docs/TESTNET_RUNBOOK.md
```

Planned **CLI / Docker** flows (roadmap — not all commands exist in this tree yet):

```bash
# Illustrative only — verify availability in your distribution package
# cp .env.example .env
# docker compose up -d
# npx karma-agent init
# npx karma-agent connect --network testnet
```

### This repository today (contracts + static tools)

```bash
forge build
forge test -q
```

Off-chain Trusted Agent demo (receipts → evidence → structural verify → settlement plan):

```bash
python3 scripts/trusted_agent_minimal_flow.py
```

Static Agent Guard / console-style UI (local file server):

```bash
python3 -m http.server 8787
# http://127.0.0.1:8787/apps/agent-service-guard/frontend/index.html
```

### Product web surfaces (static)

| Surface | Path |
|---------|------|
| Marketing website | `apps/website/index.html` |
| Console shell | `apps/console/index.html` |
| Developer / local deploy | `apps/developer-portal/index.html` |

Optional Docker host: `docker compose -f docker/docker-compose.example.yml up` (see `docker/README.md`).

---

## License and usage policy

- Community/open-source license: **AGPL-3.0-only** (see `LICENSE`)  
- Commercial license: available on request (see `docs/LICENSING.md`)  
- Brand and name usage: see `TRADEMARK_POLICY.md`  
- Open source acknowledgements: `OPEN_SOURCE_ACKNOWLEDGEMENTS.md`, `OPEN_SOURCE_NOTICE.md`, `THIRD_PARTY_COMPONENTS.md`

---

## Core protocol (Solidity)

- `NonCustodialAgentPayment`: bill lifecycle, dual-side lock model, dispute and batch settlement  
- `SettlementEngine`: EIP-712 quote settlement path  
- `AuthTokenManager`: replay-safe auth token consumption  
- `KYARegistry`: DID registration surface  
- `CircuitBreaker`: pause / risk controls  

Prerequisites: Foundry (`forge`, `cast`). Install `forge-std` into `lib/` for tests (`forge install foundry-rs/forge-std`).

---

## Documentation map (selected)

| Topic | Doc |
|-------|-----|
| Public vs private boundary | `docs/PUBLIC_PRIVATE_OPERATIONS.md` |
| Trusted Agent runtime (public adapter) | `docs/PUBLIC_ALIGNMENT_REPORT.md`, `docs/TESTNET_RUNBOOK.md` |
| Testnet execution checklist | `docs/TESTNET_EXECUTION_CHECKLIST.md` |
| Developer execution order & priorities | `docs/DEVELOPER_EXECUTION_PLAN.md` |
| Product security & console requirements | `docs/PRODUCT_SECURITY_REQUIREMENTS.md` |
| Private repository README template | `docs/README_PRIVATE.md` |
| Security contact | `SECURITY.md` |
| OpenAPI (contract-first) | `openapi/karma-v1.yaml` |

A longer historical index of ops / proof / CI commands still exists across `docs/COMMANDS.md`, `docs/COMMAND_MAP_V01.md`, and related make targets where applicable.

---

## Security

- Vulnerability reporting: `SECURITY.md`  
- Public baseline guard: `make security-baseline-guard` (when Make targets are wired in your checkout)

---

## Governance

- `CONTRIBUTING.md`  
- `NOTICE`  
- `TRADEMARK_POLICY.md`

---

## Agent Service Guard (public sub-project)

Entry: `apps/agent-service-guard/frontend/index.html`  
Details: `apps/agent-service-guard/README.md`
