# Open source notice — Karma (public repository)

This file is a **short, distribution-friendly notice**. For narrative context and architecture boundaries, see **`OPEN_SOURCE_ACKNOWLEDGEMENTS.md`**. For a **component-oriented inventory**, see **`THIRD_PARTY_COMPONENTS.md`**.

---

## 1. Karma project license

The Karma public repository is offered under the terms of the **`LICENSE`** file at the root of this repository (GNU Affero General Public License v3, unless otherwise stated in-file for specific paths). **Do not remove or replace** that file when redistributing this codebase.

---

## 2. Third-party and upstream software

This repository **builds upon and ships alongside** multiple open-source components and ecosystems, including but not limited to:

- **Ethereum** standards, tooling, and reference implementations  
- **Foundry** (`forge`, `cast`, …) and commonly **forge-std** test utilities  
- **Python** runtime and standard tooling used by scripts and tests  
- **Node.js** tooling, including **ethers.js** and **Playwright** (dev dependency for tests)  
- Optional **Web3.py** for testnet scripting (`requirements-testnet.txt`)

Some other technologies (for example **OpenManus**, **LangGraph**, **FastAPI**, **SQLAlchemy**, **Redis**, **Celery**, **Prometheus**, **Grafana**) are part of the **broader integration ecosystem** for agent systems that may connect to Karma; they are **acknowledged** in `OPEN_SOURCE_ACKNOWLEDGEMENTS.md` even when **not vendored** as direct dependencies in this tree.

Each component remains under **its own license**. **Upstream attribution must be preserved** in accordance with those licenses (including notices embedded in vendored or generated artifacts, where applicable).

---

## 3. Trademarks

Product and project names (including **Ethereum**, **Foundry**, **OpenZeppelin**, **Playwright**, and others) may be trademarks of their respective owners. Use of a name in this repository does not imply endorsement.

---

## 4. No warranty

Open-source components are provided by their authors under the terms of their licenses, **without warranty** unless explicitly stated otherwise. Karma’s maintainers provide this repository under the Karma `LICENSE` and do not warrant third-party components.

---

## 5. Contact

For **attribution, licensing, or usage** questions involving upstream projects, please contact the **Karma maintainers** through the public channels published for this repository. For **security-sensitive** licensing correspondence, follow `SECURITY.md`.

---

*This notice is informational and does not constitute legal advice.*
