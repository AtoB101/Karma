# Karma Main Chain Map (主链路分类)

This document is the single source of truth for what belongs on the **main chain**
(core business loop) versus support / scratch. It exists so the main chain stays
clean while nothing is deleted: scratch artifacts are kept on disk in `scratch/`
(git-ignored) instead of being removed.

## Principles

1. Never delete in a cleanup. Move scratch artifacts to `scratch/`.
2. The main chain is the minimal set that runs the protocol loop:
   `lock -> bind -> verify -> settle/finalize -> dispute`.
3. A module belongs on the main chain only if the loop breaks without it.
4. Removed-but-recoverable code lives in git history; restore via `git checkout <rev> -- <path>`.

## Tiers

| Tier | Meaning | Location | Committed? |
|------|---------|----------|-----------|
| T1 主链路 | Core protocol loop | repo root | yes |
| T2 支撑 | Support: verification, infra, adapters | repo root | yes |
| T3 临时 | Probe / scratch artifacts | `scratch/` | no (git-ignored) |

## T1 — 主链路 (Core loop)

- `karma-core/` — Solidity protocol: `contracts/core/KarmaBilateral.sol` + registries/evidence/scoring.
- `api/` — FastAPI public routes (bilateral, arbitration, settlement, trade, evidence, verifier_network, ...).
- `services/chain/` — on-chain settlement adapter (Bilateral only).
- `services/settlement_bridge/` — settlement bridge.
- `services/verification_engine/` — verification engine.
- `services/identity_gateway/` — identity gateway.
- `decentralized_verifier/` — verifier node/attestation/challenge models and rules
  (imported by `api/routes/arbitration.py`, `api/routes/verifier_network.py`,
  `evidence_runtime/`, `services/bond_slash.py`, `services/settlement_reversal.py`,
  `sdk/verifier.py`, `worker/tasks.py`).
- `evidence_runtime/` — receipts, bundles, structural verify, Bilateral plan builder.
- `core/` — schemas + settlement engine.
- `db/` — ORM + Alembic migrations.
- `sdk/` — Python SDK (`from karma import KarmaClient, KarmaRuntime`).
- `packages/karma-sdk`, `packages/sdk`, `packages/karma-runtime-sdk` — client SDKs.
- `apps/console/` — operator console.
- `tests/` — unit + integration tests (incl. `tests/test_verifier_network/`).
- `scripts/acceptance/` — full-chain / adversarial gates.
- `docs/` + `openapi/` + `deploy/` + `docker/` + `.github/` + `config/` + `schemas/` + `abi/`.

## T2 — 支撑 (Support)

- `certora/` — formal verification specs.
- `security/` — security policy packs.
- `infra/` — infrastructure configs.
- `worker/` — background worker.
- `examples/` — example scenarios.
- `agents/` — agent-side adapters.
- `test/` — legacy top-level test directory.
- `packages/karma-connect`, `karma-openclaw`, `karma-openmanus`, `karma-mcp`,
  `karma-mcp-server`, `karma-a2a-bridge`, `karma_billing`, `karma_security`,
  `karma_solana`, `evidence-schema` — bridges/adapters and auxiliary packages.

## T3 — 临时 (Scratch)

- `scratch/` — git-ignored, preserved on disk only: root probe scripts
  (`__probe_net.py`, `_patch_settle_op.py`, ...), the nested `_karma-console-0479da76`
  clone, and `.bak` files.

## Merge-back procedure (后期合并)

```bash
# Any earlier commit's file back to the tree
git checkout <rev> -- <path>
```

## Verification

Run `./scripts/verify-main-chain.sh` to fail the build if:

- any `__*.py` / `_*.py` / `*.bak` probe file leaks onto the main chain;
- `scratch/` or `karma-core/contracts/lib/` is not git-ignored.
