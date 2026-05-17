# Phase 1 live test — OpenClaw + OpenManus

## Quick smoke (HTTP only)

```bash
# Terminal 1 — API
uvicorn api.app:app --reload --port 8000

# Terminal 2 — seed + smoke (after DB migrate)
export KARMA_RUNTIME_URL=http://127.0.0.1:8000
export KARMA_API_KEY=karma_buyer-demo_secret
python3 scripts/acceptance/phase1_claw_manus_smoke.py \
  --buyer-id buyer-demo \
  --seller-id seller-demo \
  --skip-launch
```

Full launch requires seeded policies, runtime keys, and capacity — see `docs/PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md`.

## OpenClaw MCP

```bash
pip install -e ../../packages/karma-openclaw
cp ../openclaw-dual-agent/seller.env.example ./seller.env
# edit KARMA_API_KEY
set -a && source seller.env && set +a
karma-openclaw-mcp
```

Example tool sequence after policies are set:

1. `karma_launch_trade_order` (buyer key)  
2. `karma_get_handoff_draft`  
3. `karma_confirm_handoff` (buyer + seller)  
4. `karma_submit_execution_receipt` (seller key + handoff)

## OpenManus

**BFF path:** `examples/openmanus-adapter/README.md`  
**Runtime path:** `KarmaRuntimeClient` in `packages/karma-openmanus/README.md`
