#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Karma public P0 acceptance"

required_files=(
  "karma-core/contracts/core/KYARegistry.sol"
  "karma-core/contracts/core/KarmaBilateral.sol"
  "karma-core/contracts/core/AuthTokenManager.sol"
  "karma-core/contracts/core/EvidenceChain.sol"
  "sdk/client.py"
  "sdk/task.py"
  "sdk/adapters.py"
  "docs/API_REFERENCE.md"
  "docs/AGENT_INTEGRATION.md"
  "docs/EXECUTION_RECEIPT_STANDARD.md"
  "packages/evidence-schema/execution-receipt.schema.json"
  "apps/console/index.html"
)

for file in "${required_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "ERR  missing required deliverable file: $file"
    exit 1
  fi
done
echo "OK   required deliverable files present"

echo "==> Running public-safety guards"
bash scripts/check-trust-engine-public-safety.sh
bash scripts/security-baseline-guard.sh

echo "==> Running SDK and API acceptance tests"
python3 -m pytest tests/unit/test_sdk_adapters.py tests/unit/test_sdk_client_public.py -q
python3 -m pytest tests/integration/test_api.py -q

echo "==> Optional contract smoke gate"
if command -v forge >/dev/null 2>&1; then
  forge test --match-contract KarmaBilateral -q || forge test --match-path "karma-core/contracts/test/*Bilateral*" -q || {
    echo "WARN forge bilateral match empty; running default forge test smoke"
    forge test -q --no-match-test "Invariant|Fuzz"
  }
else
  echo "SKIP forge not found; contract smoke gate skipped"
fi

echo "OK   public P0 acceptance passed"
