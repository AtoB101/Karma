#!/usr/bin/env bash
# Run all five Certora jobs sequentially (requires certoraRun + CERTORAKEY).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SOLC="${CERTORA_SOLC:-solc8.28}"

run() {
  local sol_path="$1"
  local cname="$2"
  local spec="$3"
  echo "=== certoraRun ${cname} ==="
  certoraRun "${sol_path}:${cname}" --verify "${cname}:${spec}" --solc "${SOLC}" "$@"
}

run karma-core/contracts/core/KYARegistry.sol KYARegistry certora/specs/KYARegistry.spec "$@"
run karma-core/contracts/core/CircuitBreaker.sol CircuitBreaker certora/specs/CircuitBreaker.spec "$@"
run karma-core/contracts/core/AuthTokenManager.sol AuthTokenManager certora/specs/AuthTokenManager.spec "$@"
run karma-core/contracts/core/SettlementEngine.sol SettlementEngine certora/specs/SettlementEngine.spec "$@"
run karma-core/contracts/core/NonCustodialAgentPayment.sol NonCustodialAgentPayment certora/specs/NonCustodialAgentPayment.spec "$@"
echo "All Certora jobs finished."
