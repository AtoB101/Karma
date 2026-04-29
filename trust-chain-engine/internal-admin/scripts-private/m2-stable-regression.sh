#!/usr/bin/env bash
set -euo pipefail

# M2 stable settlement regression helper.
#
# This script is intentionally lightweight:
# - checks Foundry availability
# - runs focused stable-settlement contract tests
# - verifies M2 docs exist
# - writes one JSON artifact for OpenClaw/support handoff
#
# Usage:
#   ./scripts/m2-stable-regression.sh
#
# Optional env:
# - OUTPUT_PATH (default: results/m2-stable-regression.json)

OUTPUT_PATH="${OUTPUT_PATH:-results/m2-stable-regression.json}"
mkdir -p "$(dirname "$OUTPUT_PATH")"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  ./scripts/m2-stable-regression.sh

Optional env:
  OUTPUT_PATH=results/m2-stable-regression.json

What this checks:
  1) M2 stable-settlement contract tests (testStableSettlement*)
  2) Required M2 evidence/profile docs exist
  3) Writes one JSON artifact for OpenClaw handoff
EOF
  exit 0
fi

if ! command -v forge >/dev/null 2>&1; then
  echo "ERR: forge not found. Install Foundry first."
  echo "Hint: https://book.getfoundry.sh/getting-started/installation"
  exit 1
fi

echo "==> Running focused M2 stable-settlement tests"
TEST_OUTPUT="$(forge test --match-test "testStableSettlement" -vv 2>&1 || true)"
echo "$TEST_OUTPUT"

if printf "%s" "$TEST_OUTPUT" | rg -q "0 failed"; then
  TEST_STATUS="passed"
else
  TEST_STATUS="failed"
fi

DOC_STATUS="passed"
for p in \
  "docs/M2_0_STABLE_SETTLEMENT_PROFILE_V01.md" \
  "docs/EVIDENCE_SCHEMA_V01.md"
do
  if [[ ! -f "$p" ]]; then
    DOC_STATUS="failed"
  fi
done

if [[ "$TEST_STATUS" == "passed" && "$DOC_STATUS" == "passed" ]]; then
  STATUS="passed"
else
  STATUS="failed"
fi

cat > "$OUTPUT_PATH" <<EOF
{
  "status": "${STATUS}",
  "testStatus": "${TEST_STATUS}",
  "docStatus": "${DOC_STATUS}",
  "checkedTests": [
    "testStableSettlementTokenGateBlocksNonAllowedToken",
    "testStableSettlementMinAmountBlocksSmallBills",
    "testStableSettlementAllowedTokenAndAmountPasses"
  ],
  "checkedDocs": [
    "docs/M2_0_STABLE_SETTLEMENT_PROFILE_V01.md",
    "docs/EVIDENCE_SCHEMA_V01.md"
  ],
  "generatedAt": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF

echo
echo "M2 stable regression status: ${STATUS}"
echo "Artifact: ${OUTPUT_PATH}"

if [[ "$STATUS" != "passed" ]]; then
  exit 1
fi
