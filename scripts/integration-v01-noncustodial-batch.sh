#!/usr/bin/env bash
set -euo pipefail

# Non-custodial + batch + fuses one-command integration check.
#
# Required env vars:
# - ETH_RPC_URL
# - NON_CUSTODIAL_ADDRESS
# - TOKEN_ADDRESS
# - BUYER_PRIVATE_KEY
# - SELLER_PRIVATE_KEY
#
# Optional:
# - OWNER_PRIVATE_KEY          # if provided, script sets fuses to: mode=true, breaker=false
# - BILL_AMOUNT                # default: 100
# - LOCK_AMOUNT                # default: BILL_AMOUNT * 20
# - BILL_TTL_SECONDS           # default: 3600
# - BATCH_MAX_BILLS            # default: 0 (all)
# - PROOF_HASH                 # default: ipfs://proof-integration-v1
# - INTEGRATION_OUTPUT_PATH    # default: results/integration-noncustodial-batch.json
#
# Usage:
# ETH_RPC_URL=... NON_CUSTODIAL_ADDRESS=... TOKEN_ADDRESS=... \
# BUYER_PRIVATE_KEY=... SELLER_PRIVATE_KEY=... \
# ./scripts/integration-v01-noncustodial-batch.sh

if [[ -z "${ETH_RPC_URL:-}" || -z "${NON_CUSTODIAL_ADDRESS:-}" || -z "${TOKEN_ADDRESS:-}" || -z "${BUYER_PRIVATE_KEY:-}" || -z "${SELLER_PRIVATE_KEY:-}" ]]; then
  echo "Missing required env vars: ETH_RPC_URL / NON_CUSTODIAL_ADDRESS / TOKEN_ADDRESS / BUYER_PRIVATE_KEY / SELLER_PRIVATE_KEY"
  exit 1
fi

INTEGRATION_OUTPUT_PATH="${INTEGRATION_OUTPUT_PATH:-results/integration-noncustodial-batch.json}"

echo "Running non-custodial integration check..."
echo "Non-custodial: ${NON_CUSTODIAL_ADDRESS}"
echo "Token        : ${TOKEN_ADDRESS}"

RPC_URL="$ETH_RPC_URL" \
NON_CUSTODIAL_ADDRESS="$NON_CUSTODIAL_ADDRESS" \
TOKEN_ADDRESS="$TOKEN_ADDRESS" \
BUYER_PRIVATE_KEY="$BUYER_PRIVATE_KEY" \
SELLER_PRIVATE_KEY="$SELLER_PRIVATE_KEY" \
OWNER_PRIVATE_KEY="${OWNER_PRIVATE_KEY:-}" \
BILL_AMOUNT="${BILL_AMOUNT:-100}" \
LOCK_AMOUNT="${LOCK_AMOUNT:-}" \
BILL_TTL_SECONDS="${BILL_TTL_SECONDS:-3600}" \
BATCH_MAX_BILLS="${BATCH_MAX_BILLS:-0}" \
PROOF_HASH="${PROOF_HASH:-ipfs://proof-integration-v1}" \
INTEGRATION_OUTPUT_PATH="$INTEGRATION_OUTPUT_PATH" \
npx tsx examples/v01-noncustodial-batch-integration.ts

echo
echo "Integration PASSED."
echo "Artifact=${INTEGRATION_OUTPUT_PATH}"
