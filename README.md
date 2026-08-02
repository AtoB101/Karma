# Karma

Non-custodial bilateral escrow + evidence layer for AI agent commerce.

**Core loop:** Lock USDC → mint Bill Token (1:1) → bind buyer + agent bills → verify delivery → settle / finalize → burn bills, release USDC.

---

## Where to start (developers)

| Goal | Path |
|------|------|
| On-chain protocol | `karma-core/contracts/core/KarmaBilateral.sol` (+ 8 supporting contracts) |
| Public HTTP API | `api/` → run with `uvicorn api.app:app` |
| Operator console | `apps/console/` |
| Off-chain capacity / vouchers / P1–P8 | `services/` + `docs/AGENT_P*_*.md` |
| Evidence + settlement plans | `evidence_runtime/` (maps to Bilateral, not legacy NCPA) |
| On-chain adapter | `services/chain/settlement_adapter.py` → **KarmaBilateral only** |
| Python SDK | root `sdk/` (`from karma import KarmaClient, KarmaRuntime`) |
| TS HTTP SDK | `packages/sdk` |
| On-chain TS/Python client | `packages/karma-sdk` |
| Tests / acceptance | `tests/` + `scripts/acceptance/` |
| **Pilot E2E (Sepolia)** | [`docs/PILOT_E2E_PATH.md`](docs/PILOT_E2E_PATH.md) |

**Do not use:** legacy NonCustodialAgentPayment / SettlementEngine narratives in old docs — active path is Bilateral.

---

## Quickstart

**API (local)**

```bash
python3 -m pip install -e ".[dev]"
uvicorn api.app:app --reload --port 8000
```

**Contracts**

```bash
forge build
forge test -q
```

**Python client sketch**

```python
from karma import KarmaClient
# HTTP: capacity, vouchers, settlement, evidence — see docs/API_REFERENCE.md
```

**On-chain Bilateral sketch**

```solidity
function lock(address token, uint256 amount) external returns (uint256 billId);
function bind(uint256 buyerBillId, uint256 agentBillId, bytes32 scopeHash) external returns (uint256 bindingId);
function settle(uint256 bindingId, bytes32 proofHash) external;
function finalizeSettle(uint256 bindingId) external;
```

---

## Repo map

```text
api/                 FastAPI public routes (P1–P8, capacity, settle, evidence…)
services/            Business logic + chain/settlement_adapter (Bilateral)
evidence_runtime/    Receipts, bundles, structural verify, Bilateral plan builder
karma-core/          Solidity contracts (KarmaBilateral + registries/evidence/scoring)
apps/console/        Owner/operator UI
apps/karma_bff/      Integration BFF (HMAC) for orchestrators
sdk/ + packages/     Client SDKs and agent bridges (OpenClaw/OpenManus/x402…)
db/                  ORM + Alembic migrations
tests/               Unit + integration
scripts/acceptance/  Full-chain / adversarial gates
docs/                Protocol plates & integration guides
```

---

## Verify before PR

```bash
# Python acceptance
bash scripts/run_public_acceptance_tests.sh -q --tb=short

# Full-chain audit gate (when deps available)
bash scripts/acceptance/full_chain_audit_gate.sh

# Adversarial whole-project suite
python3 scripts/acceptance/adversarial_whole_project_suite.py

# Contracts
forge test -q
```

---

## Identity & bill model (short)

- **Bills:** lock mints 1:1 Bill Tokens; states `MINTED → BOUND → BURNED`; invariant `supply == locked`.
- **Bindings:** `ACTIVE → FINALIZING → SETTLED | DISPUTED | …`
- **Identity:** master wallet + up to **3** on-chain SubAgents; off-chain sub-identities capped separately (see API).

*Non-custodial. Math settles, not humans.*
