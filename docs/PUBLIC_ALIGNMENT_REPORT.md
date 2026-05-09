# Public alignment report — Trusted Agent Runtime on Karma

**Version:** V1.0 (MVP)  
**Scope:** Karma public repository only. This document is the outcome of **Phase 1 — Alignment** before expanding surface area.

## Executive summary

Trusted Agent Runtime is an **integration and documentation layer** on top of existing Karma settlement and evidence semantics. The public repo **must not** introduce a second escrow/settlement state machine, a second evidence system, or private risk/arbitration logic.

| Category | Count (high level) |
|----------|-------------------|
| KEEP | Core contracts, OpenAPI contract, existing evidence/proofHash semantics |
| ADAPT | Path names, SDK layout, HTTP services (map plan → actual tree) |
| MERGE | New runtime modules alongside `sdk/`, `scripts/`, `docs/` |
| DELETE | N/A (no duplicate subsystem identified to remove) |
| PRIVATE_ONLY | Risk weights, thresholds, arbitration formulas, engine-only APIs |

---

## Repository map (plan → actual)

| Plan / mental model | Actual location (public) |
|---------------------|--------------------------|
| `contracts/` | `karma-core/contracts/` (`NonCustodialAgentPayment`, `SettlementEngine`, libraries, interfaces) |
| `settlement/` (code tree) | **No** standalone package; settlement is **contract-defined** (`INonCustodialAgentPayment`, `SettlementEngine`) |
| `evidence/` (code tree) | `docs/evidence-bundle-standard.md`, `openapi/karma-v1.yaml` (`EvidenceObject`, verify routes), Guard UI references |
| `schemas/` | OpenAPI components + markdown standards; new: `trusted_agent_runtime` dataclasses (Python, stdlib) |
| `api/` implementation | **Contract-first** `openapi/karma-v1.yaml`; full server may live elsewhere or Karma2 — **ADAPT** |
| `tests/` | Root `tests/` (Playwright, etc.); new: `tests/test_trusted_agent_runtime.py` |

---

## KEEP (do not replace or fork)

1. **`NonCustodialAgentPayment`** — bill lifecycle, `lockFunds` / `createBill` / `confirmBill` / `disputeBill` / payout / dispute resolution; `proofHash` (`string`) and `scopeHash` (`bytes32`) remain the on-chain evidence anchors.
2. **`SettlementEngine`** — EIP-712 quote settlement path; separate from bill flow but part of the same public settlement story.
3. **OpenAPI** — `openapi/karma-v1.yaml` as the public HTTP contract for evidence/payment-intent shapes where applicable.
4. **Public/private boundary docs** — e.g. `docs/PUBLIC_PRIVATE_OPERATIONS.md`, `VISIBILITY_MAP.md`, Guard hardening docs.
5. **Evidence bundle standard (public field names)** — `docs/evidence-bundle-standard.md` (Guard-oriented); adapters **merge** into compatible digests rather than inventing a competing on-chain standard.

---

## ADAPT (implement as thin mapping)

1. **Trusted Agent file layout** — Plan suggested `src/karma/agents/`; repo has no `src/` app tree. **MVP:** Python package `trusted_agent_runtime/` at repository root (**stdlib** for receipt/evidence path) + `scripts/trusted_agent_minimal_flow.py`; **optional** `web3` via `requirements-testnet.txt` for Phase 3 JSON-RPC.
2. **Execution receipts → `proofHash`** — `proofHash` is a **string** on-chain; MVP encodes a deterministic public pointer: `karma-ta:v1/sha256/<64-hex>` derived from canonical evidence bundle JSON (see `trusted_agent_runtime/evidence_adapter.py`).
3. **`scopeHash`** — Task contract / policy commitment: MVP uses **SHA256** (64-hex, `0x`-prefixed for calldata) over canonical task JSON — a valid `bytes32`-sized value on-chain; Solidity integrators may prefer `keccak256` for strict EVM parity.
4. **Verification** — Public repo exposes **structural** verification only (hash chain, ordering, completeness). **No** production risk scoring in public (see PRIVATE_ONLY).
5. **Database / receipt persistence** — No new production DB in public MVP; **InMemory** receipt store only (`trusted_agent_runtime/receipt_store.py`).

---

## MERGE (coexist with existing artifacts)

1. **`sdk/agent-service-guard-example/`** — Remains the JS example for Guard; Trusted Agent runtime is **parallel** (Python) until a unified SDK is justified.
2. **`scripts/`** — `trusted_agent_minimal_flow.py`, `testnet_full_flow.py`, and stepwise `testnet_lock.py` / `testnet_create_bill.py` / `testnet_confirm.py` / `testnet_payout.py` alongside existing smoke/guard scripts.
3. **`docs/`** — This report + future `TRUSTED_AGENT_*` docs (Phase 4 documentation expansion); no conflict with existing roadmap docs.

---

## DELETE

- **None required for MVP.** Any future duplicate “second escrow” or “second evidence chain” **must not be merged**; visibility CI already guards public boundaries (`scripts/visibility-guard.sh`).

---

## PRIVATE_ONLY (must not appear in public logic)

1. Risk weights, rate limits beyond structural counts, reputation formulas.
2. Arbitration **policy** beyond what the chain exposes (arbitrator addresses, on-chain dispute state).
3. Implementations of reserved private engine routes (`/risk/check`, etc.) — **interfaces only** in public.
4. Production secrets, API keys, private keys, real `public-config.json` for WalletConnect.
5. Long-term receipt storage in a production database — **operational** concern for Karma2 or deployer infrastructure, not the public MVP.

---

## Phase gates (execution order)

| Phase | Goal | Status (this branch) |
|-------|------|------------------------|
| 1 | Alignment reports (this file + `PRIVATE_ALIGNMENT_REPORT.md`) | **Done** |
| 2 | Offchain minimal flow: task → receipts → bundle → `proofHash` mapping → simulated settlement intents | **Implemented** (`trusted_agent_runtime/`, `scripts/trusted_agent_minimal_flow.py`, tests) |
| 3 | Testnet scripts + tx hash writeback + hybrid mode | **Implemented** — `scripts/testnet_*.py`, `trusted_agent_runtime/testnet_client.py`, `requirements-testnet.txt`, `docs/TESTNET_RUNBOOK.md`, `.env.testnet.example` |
| 4 | Stress tests (100/500 agents) | **Deferred** |

---

## How to run the MVP (Phase 2)

```bash
cd /path/to/Karma
python3 scripts/trusted_agent_minimal_flow.py
python3 -m unittest tests.test_trusted_agent_runtime -v
```

Artifacts are written under `results/trusted-agent-demo/` (directory is gitignored via `results/`; create it automatically or use `--output-dir`).

## Phase 3 — hybrid / testnet (minimal)

```bash
pip install -r requirements-testnet.txt
python3 scripts/testnet_full_flow.py --output-dir results/trusted-agent-hybrid
# With funded env + keys:
python3 scripts/testnet_full_flow.py --output-dir results/trusted-agent-hybrid --send
```

See **`docs/TESTNET_RUNBOOK.md`** for env vars, per-step scripts, and `tx_hash` / `chain_id` writeback format.

---

## Sign-off criteria (public MVP)

- [x] No second settlement contract or state machine.
- [x] No second on-chain evidence system; bundles map into existing `proofHash` / digest semantics.
- [x] Runtime is replaceable (OpenManus / LangGraph remain **out of band**; only hooks/receipt schema in public repo).
- [x] Structural verification only; no private scoring.
- [x] Phase 3: optional real `tx_hash` via `scripts/testnet_full_flow.py --send` + JSONL writeback (`hybrid_tx_log.jsonl`).
