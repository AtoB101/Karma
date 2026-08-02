# Agent ↔ Agent test (落地路径)

Goal: two agents complete a **Phase-1 trade launch** to `execution_started`
(off-chain settlement mode). No Sepolia RPC required for this land path.

## One command

```bash
cp deploy/.env.local-openclaw.example .env
set -a && source .env && set +a

# Starts API if needed when KARMA_START_API=true
KARMA_START_API=true bash scripts/acceptance/local_dual_agent_gate.sh
```

Expect: `LOCAL DUAL-AGENT GATE: PASS` and smoke lines
`OK launch execution_started` + `OK idempotent replay`.

## What the gate does

1. **Seed** buyer + seller (`scripts/seed_phase1_dual_agents.py`)
   - automation policy (`preauth` + `auto_execute_pipeline`)
   - active Runtime Key rows
   - buyer capacity credits
   - seller trusts buyer + auto-accept
   - bootstrap API keys → `.env.phase1.local`
2. **Health** check (or start uvicorn when `KARMA_START_API=true`)
3. **Launch** via `phase1_claw_manus_smoke.py` (buyer API key)
   - `POST /v1/trade/orders/launch` → `execution_started`
   - idempotent replay with same `Idempotency-Key`

## Manual steps (same spine)

```bash
set -a && source deploy/.env.local-openclaw.example && set +a
python3 scripts/seed_phase1_dual_agents.py
uvicorn api.app:app --host 127.0.0.1 --port 8000   # other terminal
set -a && source .env.phase1.local && set +a
python3 scripts/acceptance/phase1_claw_manus_smoke.py \
  --buyer-id "$KARMA_BUYER_IDENTITY_ID" \
  --seller-id "$KARMA_SELLER_IDENTITY_ID" \
  --require-execution-started
```

## OpenClaw / OpenManus (optional overlay)

After the HTTP land gate is green:

```bash
pip install -e "./packages/karma-openclaw[dev]"
# Buyer agent process
KARMA_RUNTIME_URL=http://127.0.0.1:8000 \
KARMA_API_KEY="$KARMA_BUYER_API_KEY" karma-openclaw-mcp

# Seller agent process (second terminal)
KARMA_RUNTIME_URL=http://127.0.0.1:8000 \
KARMA_API_KEY="$KARMA_SELLER_API_KEY" karma-openclaw-mcp
```

OpenManus Runtime tools use the same `KarmaRuntimeClient.launch_trade_order` path.

## Out of scope for this land

| Item | Where |
|------|--------|
| Sepolia Bilateral finalize | `docs/PILOT_E2E_PATH.md` |
| Public testnet security gates | `docs/SECURITY_RELEASE_GATES.md` + `testnet_claw_manus_gate.sh` |
| Full SETTLED (buyer-accept after delivery) | Console Payments or MCP receipt path after launch |

## Related

- Pipeline integration tests: `tests/integration/test_trade_order_pipeline_launch.py`
- Checklist: `docs/PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md`
- Local env template: `deploy/.env.local-openclaw.example`
