# Karma Main Chain Map (主链路分类)

This document is the single source of truth for what belongs on the **main chain**
(core business loop) versus what is support / experimental / legacy. It exists so the
main chain stays clean while nothing is deleted: non-core code is moved to a holding
area and can be merged back with one command.

## Principles

1. Never delete in a cleanup. Move to `legacy/`, `experimental/`, or `scratch/`.
2. The main chain is the minimal set that runs the protocol loop:
   `lock -> bind -> verify -> settle/finalize -> dispute`.
3. A module belongs on the main chain only if the loop breaks without it.
4. Everything preserved can be restored by moving files back to their original path.

## Tiers

| Tier | Meaning | Location | Committed? |
|------|---------|----------|-----------|
| T1 主链路 | Core protocol loop | repo root (`karma-core/`, `api/`, `services/`, ...) | yes |
| T2 支撑 | Support: verification, infra, adapters | repo root (`certora/`, `security/`, `packages/`, ...) | yes |
| T3 实验 | Experimental / independent product lines | `experimental/` + in-place miniapp track | yes |
| T4 遗留/临时 | Superseded or scratch artifacts | `legacy/` (committed), `scratch/` (ignored) | legacy yes / scratch no |

## T1 — 主链路 (Core loop)

- `karma-core/` — Solidity protocol: `contracts/core/KarmaBilateral.sol` + registries/evidence/scoring.
- `api/` — FastAPI public routes. Active: `bilateral.py`, `trade.py`, `settlement.py`,
  `arbitration.py`, `evidence.py`, `contracts.py`, `agents.py`, `identities.py`,
  `runtime_gateway.py`, `delivery_verification.py`, `payment_codes.py`, `payment_intents.py`,
  `reputation.py`, `vouchers.py`, `x402.py`, `verify.py`, `openclaw.py`, `orchestration.py`.
- `services/chain/` — on-chain settlement adapter (Bilateral only).
- `services/settlement_bridge/` — settlement bridge.
- `services/verification_engine/` — verification engine.
- `services/identity_gateway/` — identity gateway.
- `evidence_runtime/` — receipts, bundles, structural verify, Bilateral plan builder.
- `core/` — schemas + settlement engine.
- `db/` — ORM + Alembic migrations `0001`-`0039`.
- `sdk/` — Python SDK (`from karma import KarmaClient, KarmaRuntime`).
- `packages/sdk` — TypeScript HTTP SDK.
- `packages/karma-sdk` — on-chain TS/Python client.
- `packages/karma-runtime-sdk` — agent runtime SDK.
- `apps/console/` — operator console (new `console-*.js` + `pages/*.html` structure).
- `tests/` — unit + integration tests.
- `scripts/acceptance/` — full-chain / adversarial gates.
- `docs/` — public docs (active-path docs only).
- `openapi/` — API spec.
- `deploy/` + `docker/` + `.github/` — deployment and CI.
- `config/` + `schemas/` + `abi/` — configuration, schemas, ABIs.

## T2 — 支撑 (Support)

- `certora/` — formal verification specs (run by `scripts/certora-verify.sh`).
- `security/` — security policy packs.
- `infra/` — infrastructure configs.
- `worker/` — background worker.
- `examples/` — example scenarios and scenario packs.
- `agents/` — agent-side adapters.
- `test/` — legacy top-level test directory (superset of `tests/`; keep until merged).
- `packages/karma-connect`, `karma-openclaw`, `karma-openmanus`, `karma-mcp`,
  `karma-mcp-server`, `karma-a2a-bridge`, `karma_billing`, `karma_security`,
  `karma_solana`, `evidence-schema` — bridge/adapters and auxiliary packages.

## T3 — 实验 / 独立产品线 (Experimental)

- `experimental/decentralized_verifier/` — decentralized verifier network (0 active
  validators; not required for the core loop). Self-contained, no imports from main chain.
- `services/miniapp_commerce/`, `services/miniapp_registry/`, `services/miniapp_trust/`,
  `services/telegram/`, `apps/telegram_miniapp/` — Telegram MiniApp MVP track
  (registered in `api/app.py`; move only after removing those router registrations).

## T4 — 遗留 / 临时 (Legacy / Scratch)

- `legacy/` — committed archive of the 478 files removed from the main chain on the
  console-overhaul restructure. Preserves original relative paths. Contents include:
  - `legacy/apps/console/scripts/cyber-*.js` + `legacy/apps/console/assets/` — old cyber console.
  - `legacy/api/routes/escrow.py`, `skill_market.py`, `vouchers.py` (old), `reviews.py`,
    `developers.py`, `chat_adapters.py`, `console_*.py`, `entity_verification.py`,
    `onboarding_authorization.py`, `payment_ledger.py`, `agent_pairing.py`,
    `identity_verification.py` — removed routes.
  - `legacy/db/migrations/versions/0040_*` .. `0070_*` — removed migrations.
  - `legacy/tests/unit/*` — removed tests.
  - `legacy/docs/mcp/*`, `legacy/docs/TEE_ATTESTATION_SPEC.md`, etc. — removed docs.
  - `legacy/examples/scenario-packs/*`, `legacy/deploy/*`, `legacy/.github/workflows/*`.
- `scratch/` — ignored, preserved on disk only: root probe scripts, the nested
  `_karma-console-0479da76` git clone, and `.bak` files.

## Merge-back procedure (后期合并)

To restore a legacy item to the main chain, move it back to its original path:

```bash
# Example: bring back the old escrow route
mkdir -p api/routes
git mv legacy/api/routes/escrow.py api/routes/escrow.py

# Example: bring back the whole cyber console
git mv legacy/apps/console/scripts/cyber-actions.js apps/console/scripts/cyber-actions.js
```

To re-register a restored API route, re-add it in `api/app.py` and re-add its Alembic
migration to the chain in `db/migrations/versions/` (check `down_revision`).

## Verification

Run `./scripts/verify-main-chain.sh` to fail the build if:

- any main-chain file imports from `legacy/` or `experimental/`;
- any `__*.py` / `_*.py` temp file appears at repo root or under main-chain dirs;
- `decentralized_verifier` exists outside `experimental/`;
- `scratch/` or `karma-core/contracts/lib/` is not git-ignored.
