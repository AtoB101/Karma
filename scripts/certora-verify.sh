#!/usr/bin/env bash
# Run live Certora jobs sequentially (requires certoraRun + CERTORAKEY).
# Legacy SettlementEngine / NonCustodialAgentPayment confs were removed with NCPA.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONFS=(
  certora/conf/KYARegistry.conf
  certora/conf/CircuitBreaker.conf
  certora/conf/AuthTokenManager.conf
)

for conf in "${CONFS[@]}"; do
  echo "=== certoraRun --conf ${conf} ==="
  certoraRun --conf "${conf}" "$@"
done
echo "All Certora jobs finished."
