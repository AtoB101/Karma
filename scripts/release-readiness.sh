#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROFILE="${1:-lenient}"

echo "==> Release readiness (${PROFILE})"

echo "==> Running security baseline guard"
./scripts/security-baseline-guard.sh

echo "==> Running proof/evidence gate"
./scripts/ci-proof-gates.sh

echo "==> Running slither gate"
./scripts/slither-gate.sh --format text

echo "OK   release-readiness passed."
