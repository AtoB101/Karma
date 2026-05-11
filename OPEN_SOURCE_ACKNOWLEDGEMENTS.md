# Open source acknowledgements — Karma (public repository)

Karma’s public work stands on widely used open-source foundations. This document states **what we rely on**, **how Karma relates to upstream agent ecosystems**, and **what Karma does not claim**. It is intended for maintainers, integrators, and downstream distributions.

---

## 1. Relationship to upstream agent runtimes (architecture boundary)

**OpenManus, LangGraph, and similar projects** provide general-purpose **agent execution, orchestration, and tooling** patterns. They are not defined or owned by Karma.

In Karma’s architecture, such systems are appropriately viewed as:

- **Execution runtime / orchestration layer** — scheduling tools, managing graphs or workflows, and connecting models to external capabilities.

**Karma (this public repository and its public adapters)** focuses on **trusted execution and settlement-oriented infrastructure** layered *above* those ecosystems, including where applicable:

- Trusted execution runtime **adapters** (recording and structuring execution steps without replacing upstream runtimes)
- **Receipt** generation and integrity-oriented **evidence bundling**
- **Public structural verification** (integrity and consistency checks that do not embed private risk formulas)
- **Replay-oriented protections** at the adapter and artifact level (complementary to on-chain nonces and contract state)
- **Settlement-aware** runtime flows that map artifacts to existing Karma settlement surfaces
- **Dispute-oriented execution traces** as *structured, hashable artifacts* suitable for existing dispute workflows — **not** private arbitration logic in this repository

Karma **does not** claim to have invented upstream agent frameworks. Karma **does** aim to make it easier to connect serious agent workloads to **non-custodial settlement and evidence semantics** already expressed in the Karma core contracts and public verification boundaries.

---

## 2. Technologies and communities we acknowledge

The following are called out **by ecosystem role**. Where a component is **directly** depended on in this repository today, that is noted explicitly. Items marked *integration ecosystem* are commonly used alongside Karma-style deployments or referenced in project documentation, but **may not be vendored** in this tree; integrators should follow their own supply-chain and license reviews.

| Area | Acknowledgement |
|------|-----------------|
| **OpenManus** | *Integration ecosystem.* Referenced as an example agent runtime context in public demos and naming; not shipped as a vendored dependency of this repository. |
| **LangGraph** | *Integration ecosystem.* Often used for durable agent graphs in production systems that may call Karma settlement surfaces; not a declared runtime dependency of this repository today. |
| **FastAPI** | *Integration ecosystem.* Frequently used for HTTP services around agents and webhooks; not a declared Python dependency of this repository today. |
| **SQLAlchemy** | *Integration ecosystem.* Common persistence layer for operational stores; not a declared dependency here today. |
| **Redis** | *Integration ecosystem.* Common cache, queue backing store, and session store in agent deployments. |
| **Celery** | *Integration ecosystem.* Common distributed task queue for asynchronous agent workloads. |
| **Prometheus / Grafana** | *Integration ecosystem.* Common observability stacks for production services. |
| **Web3.py** | **Direct (optional).** Declared in `requirements-testnet.txt` for JSON-RPC and testnet scripting. |
| **ethers.js** | **Direct.** Declared in `package.json` for Node-based tooling and demos. |
| **Playwright** | **Direct (dev).** Declared in `package.json` for browser automation tests. |
| **Foundry** | **Direct (toolchain).** `foundry.toml` and Solidity tests use the Foundry toolkit; tests import **forge-std** where present in a developer’s `lib/` checkout. |
| **OpenZeppelin** | **Ecosystem / engineering practice.** Public engineering notes in this repository reference OpenZeppelin patterns as industry practice; core contracts in `karma-core/` may or may not import OpenZeppelin packages depending on revision — verify `imports` in-tree for your checkout. |
| **Python open-source ecosystem** | **Direct.** Standard library and common OSS packages used by Python modules and tests (see `THIRD_PARTY_COMPONENTS.md` for a concrete inventory). |
| **Ethereum ecosystem** | **Direct.** On-chain interfaces, ABIs, and EIP standards (including EIP-712) used in contract design and clients. |

---

## 3. Respectful statement to upstream communities

We deeply appreciate the open-source communities and maintainers whose work helped make Karma possible — including agent runtime projects, Ethereum infrastructure, Python and JavaScript tooling, testing frameworks, and security research that informs safe engineering.

If any upstream maintainer or contributor believes **attribution, licensing, or usage** should be adjusted, **please contact the Karma maintainers directly** (for example via the project’s public GitHub organisation or the contact route published in `SECURITY.md` for sensitive licensing topics).

---

## 4. What this repository does **not** contain

To avoid confusion for auditors and downstream users:

- **No private verification logic** — private risk scoring, thresholds, and policy matrices belong outside this public boundary.
- **No private arbitration formulas** — dispute *decision rules* that are commercial or sensitive are not published here.
- **No claim of exclusive originality** over general-purpose agent stacks — Karma’s novelty is in the **trusted execution artifacts and settlement alignment**, not in replacing upstream runtimes.

---

## 5. License preservation

This acknowledgement layer **does not replace** any `LICENSE` file. All existing license texts in this repository remain authoritative. Third-party components remain under their respective licenses; see `OPEN_SOURCE_NOTICE.md` and `THIRD_PARTY_COMPONENTS.md` for a concise inventory and pointers.

---

*Last updated: project maintainers — public repository release hygiene.*
