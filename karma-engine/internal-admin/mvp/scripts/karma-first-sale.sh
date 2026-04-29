#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SYMBOL="${TC_SYMBOL:-BTCUSDT}"
HOST_URL="${TC_GATEWAY_URL:-http://127.0.0.1:8822}"

if [[ ! -f ".env" ]]; then
  echo "FAIL: .env not found. Create from .env.example first."
  exit 2
fi

echo "==> 1) Simulate one paid external call"
./simulate-external-user-call.sh --host "$HOST_URL" --symbol "$SYMBOL"

echo
echo "==> 2) Verify first paid call settlement closure"
./verify-first-paid-call.sh --json | python3 - <<'PY'
import json, sys
obj = json.load(sys.stdin)
if not obj.get("ok"):
    print("FAIL: first-sale verification failed")
    print(json.dumps(obj, indent=2))
    sys.exit(2)
print("PASS: first-sale verification")
print(json.dumps({
    "callId": obj.get("callId"),
    "txHash": obj.get("txHash"),
    "chargedWei": obj.get("chargedWei"),
    "userDeltaWei": obj.get("userDeltaWei"),
    "providerDeltaWei": obj.get("providerDeltaWei"),
}, indent=2))
PY

echo
echo "==> 3) Capture proof artifact"
./capture-demo-proof.sh

echo
echo "first-sale: PASS"
