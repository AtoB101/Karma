#!/usr/bin/env bash
# Wire Bilateral ↔ karma8 FeeBridge / Treasury (main-repo ops).
# Requires: cast, addresses from karma8 deployments/<network>.json
#
# Usage:
#   export RPC_URL=...
#   export PRIVATE_KEY=...          # Bilateral admin
#   export KARMA_BILATERAL=0x...
#   export TREASURY=0x...
#   export FEE_BRIDGE=0x...
#   export SETTLEMENT_MIRROR=0x...  # optional verify
#   bash deploy/wire_feebridge.sh
set -euo pipefail

need() {
  local v="$1"
  if [[ -z "${!v:-}" ]]; then
    echo "missing env $v" >&2
    exit 1
  fi
}

need RPC_URL
need PRIVATE_KEY
need KARMA_BILATERAL
need TREASURY
need FEE_BRIDGE

echo "== Bilateral.setTreasury($TREASURY) =="
cast send "$KARMA_BILATERAL" "setTreasury(address)" "$TREASURY" \
  --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY"

echo "== Bilateral.setFeeBridge($FEE_BRIDGE) =="
cast send "$KARMA_BILATERAL" "setFeeBridge(address)" "$FEE_BRIDGE" \
  --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY"

echo "== Verify FeeBridge.core == Bilateral =="
core_onchain=$(cast call "$FEE_BRIDGE" "core()(address)" --rpc-url "$RPC_URL")
echo "FeeBridge.core: $core_onchain"
echo "expect:         $KARMA_BILATERAL"
if [[ "${core_onchain,,}" != "${KARMA_BILATERAL,,}" ]]; then
  echo "FAIL: FeeBridge.core != Bilateral — fix with karma8 WireKarmaCore / redeploy" >&2
  exit 1
fi
echo "OK: FeeBridge.core == Bilateral"

if [[ -n "${SETTLEMENT_MIRROR:-}" ]]; then
  echo "== SettlementMirror.isReporter(FeeBridge) =="
  is_rep=$(cast call "$SETTLEMENT_MIRROR" "isReporter(address)(bool)" "$FEE_BRIDGE" --rpc-url "$RPC_URL")
  echo "isReporter: $is_rep"
  if [[ "$is_rep" != "true" ]]; then
    echo "FAIL: FeeBridge is not Mirror reporter" >&2
    exit 1
  fi
  echo "OK: FeeBridge is reporter"
fi

if [[ -n "${TREASURY:-}" ]]; then
  rev=$(cast call "$TREASURY" "enableRevenueMode()(bool)" --rpc-url "$RPC_URL" || echo "n/a")
  echo "Treasury.enableRevenueMode: $rev (cold-start expect false)"
fi

echo "RESULT: OK"
echo "Reminders:"
echo "  - orderId = bytes32(bindingId)"
echo "  - developer = builder via setBindingDeveloper (else seller)"
echo "  - settle: quoteFee then collectAndRecord with exact fee"
echo "  - Verify PASS before Bilateral.settle"
echo "  - KARMA8_ECONOMY_HOST iframe /?view=miniapp"
