#!/usr/bin/env bash
set -euo pipefail

# NC-205 full pipeline:
# 1) run OpenClaw scenario
# 2) run Hermes scenario
# 3) generate CN report draft
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
# - OPENCLAW_RUN_ID            default: 001
# - HERMES_RUN_ID              default: 001
# - REPORT_OWNER               default: unknown
# - REPORT_OUTPUT_PATH         default: docs/INTEGRATION_RESULTS_REPORT_CN.generated.txt

OPENCLAW_RUN_ID="${OPENCLAW_RUN_ID:-001}"
HERMES_RUN_ID="${HERMES_RUN_ID:-001}"
REPORT_OWNER="${REPORT_OWNER:-unknown}"
REPORT_OUTPUT_PATH="${REPORT_OUTPUT_PATH:-docs/INTEGRATION_RESULTS_REPORT_CN.generated.txt}"

echo "NC-205 full pipeline started..."
echo "Step 1/3: OpenClaw scenario run"
OPENCLAW_RUN_ID_ENV="$OPENCLAW_RUN_ID"
RUN_ID="$OPENCLAW_RUN_ID_ENV" ./scripts/integration-openclaw-run.sh

echo "Step 2/3: Hermes scenario run"
HERMES_RUN_ID_ENV="$HERMES_RUN_ID"
RUN_ID="$HERMES_RUN_ID_ENV" ./scripts/integration-hermes-run.sh

echo "Step 3/3: Generate CN report draft"
OPENCLAW_RESULT_PATH="results/integration-openclaw-run-${OPENCLAW_RUN_ID}.json" \
HERMES_RESULT_PATH="results/integration-hermes-run-${HERMES_RUN_ID}.json" \
REPORT_OUTPUT_PATH="$REPORT_OUTPUT_PATH" \
REPORT_OWNER="$REPORT_OWNER" \
./scripts/generate-integration-report.sh

echo
echo "NC-205 full pipeline PASSED."
echo "OpenClaw artifact: results/integration-openclaw-run-${OPENCLAW_RUN_ID}.json"
echo "Hermes artifact  : results/integration-hermes-run-${HERMES_RUN_ID}.json"
echo "Report output    : ${REPORT_OUTPUT_PATH}"
