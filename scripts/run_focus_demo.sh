#!/usr/bin/env bash
set -euo pipefail

echo "[TrustChain] Running focused scenario flow..."
forge test --match-path "contracts/test/ScenarioFlow.t.sol" -vv

echo "[TrustChain] Focused demo completed."
