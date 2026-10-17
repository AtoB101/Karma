#!/usr/bin/env bash
# Sample on-chain vs manifest alignment (requires cast + env). Non-fatal if tools missing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="${KARMA_DEPLOYMENT_MANIFEST:-$ROOT/deployment-manifest.json}"
LOCK="${KARMA_CORE_VERSION_LOCK:-$ROOT/CORE_VERSION.lock}"

if [[ ! -f "$MANIFEST" ]]; then
  echo "SKIP no deployment-manifest.json at $MANIFEST"
  exit 0
fi

echo "== Manifest file =="
python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print('chain_id', m.get('chain_id')); c=m.get('contracts',{}); print('nc', c.get('non_custodial_agent_payment','?')[:20]+'...')" "$MANIFEST"

if [[ -f "$LOCK" ]]; then
  echo "== CORE_VERSION.lock =="
  grep -E "commit|tag" "$LOCK" || cat "$LOCK"
fi

RPC="${TESTNET_RPC_URL:-}"
NC="${NONCUSTODIAL_AGENT_PAYMENT_ADDRESS:-${KARMA_NON_CUSTODIAL_ADDRESS:-}}"
if [[ -z "$RPC" || -z "$NC" ]]; then
  echo "SKIP cast probe (set TESTNET_RPC_URL + NONCUSTODIAL_AGENT_PAYMENT_ADDRESS)"
  exit 0
fi
if ! command -v cast >/dev/null 2>&1; then
  echo "SKIP cast not installed"
  exit 0
fi

echo "== cast code size probe =="
cast code "$NC" --rpc-url "$RPC" | head -c 80
echo ""
echo "OK manifest sample checks done"
