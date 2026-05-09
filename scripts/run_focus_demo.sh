#!/usr/bin/env bash
set -euo pipefail

echo "[Karma] Running focused scenario flow..."
forge test --match-path "contracts/test/ScenarioFlow.t.sol" -vv

echo "[Karma] Focused demo completed."
