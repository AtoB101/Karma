#!/usr/bin/env bash
# Run all five Certora jobs sequentially (requires certoraRun + CERTORAKEY).
# Passes each JSON config as the first positional argument (cloud-compatible).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONFS=(
  certora/conf/KYARegistry.conf
  certora/conf/CircuitBreaker.conf
  certora/conf/AuthTokenManager.conf
  certora/conf/SettlementEngine.conf
  certora/conf/NonCustodialAgentPayment.conf
)

for conf in "${CONFS[@]}"; do
  echo "=== certoraRun ${conf} ==="
  certoraRun "${conf}" "$@"
done
echo "All Certora jobs finished."
