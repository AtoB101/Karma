#!/usr/bin/env bash
set -euo pipefail

# ETH-chain minimal smoke test for v0.1 settlement flow.
#
# Required env vars:
# - ETH_RPC_URL
# - ENGINE_ADDRESS
# - TOKEN_ADDRESS
# - PAYER_PRIVATE_KEY
# - PAYEE_ADDRESS
#
# Optional:
# - SMOKE_OUTPUT_PATH       default: results/smoke-v01-eth.json
# - CHAIN_LABEL             default: eth-like
#
# Usage:
#   ETH_RPC_URL=... ENGINE_ADDRESS=... TOKEN_ADDRESS=... \
#   PAYER_PRIVATE_KEY=... PAYEE_ADDRESS=... \
#   ./scripts/smoke-v01-eth.sh

if [[ -z "${ETH_RPC_URL:-}" || -z "${ENGINE_ADDRESS:-}" || -z "${TOKEN_ADDRESS:-}" || -z "${PAYER_PRIVATE_KEY:-}" || -z "${PAYEE_ADDRESS:-}" ]]; then
  echo "Missing required env vars: ETH_RPC_URL / ENGINE_ADDRESS / TOKEN_ADDRESS / PAYER_PRIVATE_KEY / PAYEE_ADDRESS"
  exit 1
fi

SMOKE_OUTPUT_PATH="${SMOKE_OUTPUT_PATH:-results/smoke-v01-eth.json}"
CHAIN_LABEL="${CHAIN_LABEL:-eth-like}"

echo "Running v0.1 ETH smoke test..."
echo "Engine: ${ENGINE_ADDRESS}"
echo "Token : ${TOKEN_ADDRESS}"
echo "Payee : ${PAYEE_ADDRESS}"

script_output="$(
  RPC_URL="$ETH_RPC_URL" \
  ENGINE_ADDRESS="$ENGINE_ADDRESS" \
  TOKEN_ADDRESS="$TOKEN_ADDRESS" \
  PAYER_PRIVATE_KEY="$PAYER_PRIVATE_KEY" \
  PAYEE_ADDRESS="$PAYEE_ADDRESS" \
  npx tsx examples/v01-quote-settlement.ts 2>&1
)"

tx_hash="$(printf "%s" "$script_output" | rg "Settlement tx hash:" | awk '{print $4}')"
digest="$(printf "%s" "$script_output" | rg "On-chain digest:" | awk '{print $3}')"

if [[ -z "${tx_hash}" ]]; then
  echo "Smoke test failed. Raw output:"
  echo "----------------------------------------"
  echo "$script_output"
  echo "----------------------------------------"
  exit 1
fi

mkdir -p "$(dirname "$SMOKE_OUTPUT_PATH")"
cat > "$SMOKE_OUTPUT_PATH" <<EOF
{
  "chainLabel": "${CHAIN_LABEL}",
  "engineAddress": "${ENGINE_ADDRESS}",
  "tokenAddress": "${TOKEN_ADDRESS}",
  "payeeAddress": "${PAYEE_ADDRESS}",
  "txHash": "${tx_hash}",
  "onchainDigest": "${digest}",
  "status": "passed",
  "generatedAt": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF

echo
echo "Smoke test PASSED."
echo "TX_HASH=${tx_hash}"
echo "Digest=${digest}"
echo "Artifact=${SMOKE_OUTPUT_PATH}"
