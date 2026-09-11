#!/usr/bin/env bash
# Phase 2 x402 acceptance gate (no live Sepolia).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "==> Phase 2 x402 unit + integration tests"
python3 -m pytest -q \
  tests/unit/test_x402_client.py \
  tests/unit/test_x402_security.py \
  tests/unit/test_x402_env_signing_executor.py \
  tests/integration/test_x402_pay_and_fetch.py

echo "==> Phase 2 x402 evidence benchmark (mock)"
python3 scripts/benchmark_x402_evidence_integrity.py --iterations 5

echo "OK   phase2 x402 gate finished"
