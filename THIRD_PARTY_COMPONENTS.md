# Third-party components — inventory (public repository)

This document lists **directly referenced** open-source components in the Karma public repository as surfaced by common manifest files. It is maintained for **transparency and release hygiene**, not as a legal opinion.

**Not listed here:** transitive dependency trees inside `node_modules/` (not committed to this repository) and optional developer checkouts under `lib/` (for example **forge-std**) that may exist locally but are not always tracked as source in git.

---

## 1. JavaScript / Node (`package.json`)

| Component | Role in this repo | License (typical) |
|-----------|-------------------|-------------------|
| **ethers** (`ethers`) | Node scripts / demos interacting with EVM JSON-RPC | MIT |
| **@playwright/test** | End-to-end browser tests for static frontends | Apache-2.0 |

*Verify exact versions and SPDX identifiers in `package-lock.json` for your distribution.*

---

## 2. Python (`requirements-testnet.txt` and standard library)

| Component | Role in this repo | Notes |
|-----------|-------------------|--------|
| **web3** | Optional JSON-RPC client for testnet / hybrid scripts | Declared lower bound in `requirements-testnet.txt` |
| **Python standard library** | Scripts, tests, packaging | PSF license |

Other Python packages may appear only as **transitive** installs in developer environments (for example static analysis tools in CI) and are not duplicated here exhaustively.

---

## 3. Solidity / Ethereum engineering

| Component | Role in this repo | Notes |
|-----------|-------------------|--------|
| **Foundry** | Build, test, fuzz, and gas tooling | See `foundry.toml` |
| **forge-std** | Test harness imports (`forge-std/Test.sol`, …) | Present when `lib/forge-std` is installed locally |
| **Ethereum execution specs / EVM** | Target environment for contracts | N/A (protocol) |

**OpenZeppelin Contracts:** widely used across the Ethereum ecosystem; this repository’s engineering documentation references OpenZeppelin **patterns and libraries** as common practice. **Whether** a given revision imports `@openzeppelin/*` packages is **source-level fact** — search `contracts` for imports in your checkout.

---

## 4. Integration ecosystem (not necessarily vendored here)

The following are **frequently adjacent** to Karma-style deployments or referenced in architecture discussions. They are **acknowledged** in `OPEN_SOURCE_ACKNOWLEDGEMENTS.md` and may appear in docs or examples, but **are not guaranteed** to appear as pinned dependencies in this repository:

- **OpenManus** — agent runtime / tooling ecosystem  
- **LangGraph** — graph-based agent orchestration  
- **FastAPI** — HTTP services for agents and operators  
- **SQLAlchemy** — Python ORM / DB access patterns  
- **Redis** — caching, pub/sub, queues  
- **Celery** — distributed task execution  
- **Prometheus / Grafana** — metrics and dashboards  

If your fork vendors any of the above, **extend this table** and preserve upstream notices in your distribution.

---

## 5. Preservation rule

- **Do not remove** upstream `LICENSE` files or SPDX headers required by dependencies you vendor or ship.  
- **Do not strip** copyright or attribution notices from files where those notices are legally required.

---

*Maintainers: update this inventory when root manifests change materially.*
