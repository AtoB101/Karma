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
# - RUN_BATCH_SMOKE         default: 0 (set 1 to run batch stress smoke)
# - BATCH_SIZE              default: 20
# - BATCH_DELAY_MS          default: 100
# - BATCH_OUTPUT_PATH       default: results/smoke-batch-v01-eth.json
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
RUN_BATCH_SMOKE="${RUN_BATCH_SMOKE:-0}"
BATCH_SIZE="${BATCH_SIZE:-20}"
BATCH_DELAY_MS="${BATCH_DELAY_MS:-100}"
BATCH_OUTPUT_PATH="${BATCH_OUTPUT_PATH:-results/smoke-batch-v01-eth.json}"

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

batch_status="skipped"
batch_success_count=""
batch_failure_count=""
batch_success_rate=""
batch_output_file=""
if [[ "$RUN_BATCH_SMOKE" == "1" ]]; then
  echo
  echo "Running optional batch smoke (size=${BATCH_SIZE}, delayMs=${BATCH_DELAY_MS})..."
  batch_output="$(
    RPC_URL="$ETH_RPC_URL" \
    ENGINE_ADDRESS="$ENGINE_ADDRESS" \
    TOKEN_ADDRESS="$TOKEN_ADDRESS" \
    PAYER_PRIVATE_KEY="$PAYER_PRIVATE_KEY" \
    PAYEE_ADDRESS="$PAYEE_ADDRESS" \
    BATCH_SIZE="$BATCH_SIZE" \
    DELAY_MS="$BATCH_DELAY_MS" \
    OUTPUT_PATH="$BATCH_OUTPUT_PATH" \
    npx tsx examples/v01-batch-settlement.ts 2>&1
  )"
  batch_output_file="$BATCH_OUTPUT_PATH"
  batch_success_count="$(printf "%s" "$batch_output" | rg "Success count:" | awk '{print $3}')"
  batch_failure_count="$(printf "%s" "$batch_output" | rg "Failure count:" | awk '{print $3}')"
  batch_success_rate="$(printf "%s" "$batch_output" | rg "Success rate:" | awk '{print $3}')"
  if [[ -z "${batch_success_count}" ]]; then
    echo "Batch smoke failed. Raw output:"
    echo "----------------------------------------"
    echo "$batch_output"
    echo "----------------------------------------"
    exit 1
  fi
  batch_status="passed"
fi

cat > "$SMOKE_OUTPUT_PATH" <<EOF
{
  "chainLabel": "${CHAIN_LABEL}",
  "engineAddress": "${ENGINE_ADDRESS}",
  "tokenAddress": "${TOKEN_ADDRESS}",
  "payeeAddress": "${PAYEE_ADDRESS}",
  "txHash": "${tx_hash}",
  "onchainDigest": "${digest}",
  "batchSmokeStatus": "${batch_status}",
  "batchSize": "${BATCH_SIZE}",
  "batchDelayMs": "${BATCH_DELAY_MS}",
  "batchSuccessCount": "${batch_success_count}",
  "batchFailureCount": "${batch_failure_count}",
  "batchSuccessRate": "${batch_success_rate}",
  "batchOutputPath": "${batch_output_file}",
  "status": "passed",
  "generatedAt": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF

echo
echo "Smoke test PASSED."
echo "TX_HASH=${tx_hash}"
echo "Digest=${digest}"
if [[ "$RUN_BATCH_SMOKE" == "1" ]]; then
  echo "Batch smoke status=${batch_status} success=${batch_success_count} failure=${batch_failure_count} rate=${batch_success_rate}"
  echo "Batch artifact=${BATCH_OUTPUT_PATH}"
fi
echo "Artifact=${SMOKE_OUTPUT_PATH}"
