#!/usr/bin/env bash
set -euo pipefail

# OpenClaw scenario runner (non-custodial + batch path).
#
# Required env vars:
# - ETH_RPC_URL
# - NON_CUSTODIAL_ADDRESS
# - TOKEN_ADDRESS
# - BUYER_PRIVATE_KEY
# - SELLER_PRIVATE_KEY
#
# Optional:
# - OWNER_PRIVATE_KEY
# - RUN_ID                      default: 001
# - BILL_AMOUNT                 default: 50
# - LOCK_AMOUNT                 default: 5000
# - BILL_TTL_SECONDS            default: 1800
# - BATCH_MAX_BILLS             default: 0
# - PROOF_HASH                  default: ipfs://openclaw-proof-v1
#
# Output:
# - results/integration-openclaw-run-<RUN_ID>.json

RUN_ID="${RUN_ID:-001}"
OUTPUT_PATH="results/integration-openclaw-run-${RUN_ID}.json"

echo "Running OpenClaw integration scenario..."

ETH_RPC_URL="${ETH_RPC_URL:-}" \
NON_CUSTODIAL_ADDRESS="${NON_CUSTODIAL_ADDRESS:-}" \
TOKEN_ADDRESS="${TOKEN_ADDRESS:-}" \
BUYER_PRIVATE_KEY="${BUYER_PRIVATE_KEY:-}" \
SELLER_PRIVATE_KEY="${SELLER_PRIVATE_KEY:-}" \
OWNER_PRIVATE_KEY="${OWNER_PRIVATE_KEY:-}" \
BILL_AMOUNT="${BILL_AMOUNT:-50}" \
LOCK_AMOUNT="${LOCK_AMOUNT:-5000}" \
BILL_TTL_SECONDS="${BILL_TTL_SECONDS:-1800}" \
BATCH_MAX_BILLS="${BATCH_MAX_BILLS:-0}" \
PROOF_HASH="${PROOF_HASH:-ipfs://openclaw-proof-v1}" \
INTEGRATION_OUTPUT_PATH="$OUTPUT_PATH" \
./scripts/integration-v01-noncustodial-batch.sh

echo "OpenClaw artifact=${OUTPUT_PATH}"
