#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[TrustChain]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK  ]${NC} $*"; }
warn() { echo -e "${YELLOW}[ WARN ]${NC} $*"; }
err()  { echo -e "${RED}[ FAIL ]${NC} $*"; }

cleanup() {
  if [ -n "${ANVIL_PID:-}" ]; then
    log "Stopping anvil (pid $ANVIL_PID)..."
    kill "$ANVIL_PID" 2>/dev/null || true
    wait "$ANVIL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# ── Start local Anvil (instant mining) ──
log "Starting anvil (chainid 31337, automining)..."
anvil --chain-id 31337 --silent &
ANVIL_PID=$!
sleep 2

if ! kill -0 "$ANVIL_PID" 2>/dev/null; then
  err "Anvil failed to start"
  exit 1
fi
ok "Anvil running (pid $ANVIL_PID)"

export RPC_URL="http://127.0.0.1:8545"

# ── Build contracts ──
log "Building contracts..."
forge build --force 2>&1 | tail -1

# ── Deploy contracts via forge script ──
log "Deploying contracts..."
export DEPLOYER_KEY="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

SCRIPT_OUT=$(forge script contracts/script/DeployDemo.s.sol \
  --rpc-url "$RPC_URL" \
  --broadcast \
  --private-key "$DEPLOYER_KEY" \
  2>&1) || { err "Deployment failed"; echo "$SCRIPT_OUT"; exit 1; }

# Extract JSON from console.log output
DEPLOY_JSON=$(echo "$SCRIPT_OUT" | sed -n '/DEPLOY_JSON_START/,/DEPLOY_JSON_END/p' | grep -v 'DEPLOY_JSON' | tr -d '\r')
echo "$DEPLOY_JSON" > deployment.json

if [ ! -s deployment.json ] || ! python3 -c "import json; json.load(open('deployment.json'))" 2>/dev/null; then
  err "Failed to parse deployment JSON"
  echo "$SCRIPT_OUT" | tail -30
  exit 1
fi

ok "Contracts deployed:"
python3 -c "import json; d=json.load(open('deployment.json')); [print(f'   {k}: {v}') for k,v in d.items()]"

# ── Extract ABIs ──
log "Extracting ABIs..."
python3 -c "
import json
abis = {}
for c in ['DemoToken','KYARegistry','LockPoolManager','AuthTokenManager','CircuitBreaker','BillManager']:
    with open(f'out/{c}.sol/{c}.json') as f:
        abis[c] = json.load(f)['abi']
json.dump(abis, open('abis.json','w'), indent=2)
"
ok "ABIs extracted"

# ── Install JS deps if needed ──
if [ ! -d "node_modules" ]; then
  log "Installing npm dependencies..."
  npm install
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo -e "${GREEN}  Karma MVP — Ready${NC}"
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo ""
echo -e "  ${YELLOW}npm run simulate${NC}    # Run E2E simulation"
echo -e "  ${YELLOW}npm run verify${NC}      # Verify on-chain state"  
echo -e "  ${YELLOW}npm run proof${NC}       # Generate proof artifacts"
echo -e "  ${YELLOW}make frontend${NC}      # Start web console (port 8787)"
echo -e "  ${YELLOW}npm run full${NC}        # simulate + verify + proof"
echo ""

# Keep anvil running until user Ctrl-C
log "Anvil is running. Press Ctrl-C to stop."
wait "$ANVIL_PID"
