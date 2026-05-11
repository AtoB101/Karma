#!/usr/bin/env bash
# Run all five Certora jobs sequentially (requires certoraRun + CERTORAKEY).
# Passes each JSON config as the first positional argument (cloud-compatible).
#
# Optional: export CERTORA_EXTRA_ARGS="--optimistic_fallback" (or other flags)
# if your certoraRun supports them and they are not already in the .conf file.
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
  # shellcheck disable=SC2086
  certoraRun "${conf}" ${CERTORA_EXTRA_ARGS:-} "$@"
done
echo "All Certora jobs finished."
