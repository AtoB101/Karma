#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Karma public P0 acceptance"

required_files=(
  "karma-core/contracts/core/KYARegistry.sol"
  "karma-core/contracts/_legacy/core/NonCustodialAgentPayment.sol"
  "karma-core/contracts/core/KarmaBilateral.sol"
  "karma-core/contracts/core/AuthTokenManager.sol"
  "karma-core/contracts/_legacy/core/SettlementEngine.sol"
  "sdk/client.py"
  "sdk/task.py"
  "sdk/adapters.py"
  "docs/API_REFERENCE.md"
  "docs/AGENT_INTEGRATION.md"
  "docs/EXECUTION_RECEIPT_STANDARD.md"
  "packages/evidence-schema/execution-receipt.schema.json"
  "audits/2026-05-12_security-audit.md"
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
  (cd karma-core && forge test --match-path "contracts/_legacy/test/SettlementEngine.t.sol")
else
  echo "SKIP forge not found; contract smoke gate skipped"
fi

echo "OK   public P0 acceptance passed"

