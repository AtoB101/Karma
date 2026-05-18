#!/usr/bin/env bash
# Full-chain audit gate: phase 1–3 acceptance + security regressions + reverse-rule static audit.
# No live testnet RPC required. Use testnet_claw_manus_gate.sh for Sepolia + live API.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "========================================"
echo " Karma full-chain audit gate (off-chain)"
echo "========================================"

echo ""
echo "== [1/8] Reverse-rule static audit =="
python3 scripts/acceptance/reverse_rule_audit.py

echo ""
echo "== [2/8] Phase 1 Open Wallet gate =="
bash scripts/acceptance/phase1_open_wallet_gate.sh

echo ""
echo "== [3/8] Phase 2 x402 gate =="
bash scripts/acceptance/phase2_x402_gate.sh

echo ""
echo "== [4/8] Phase 3 AP2 gate =="
bash scripts/acceptance/phase3_ap2_gate.sh

echo ""
echo "== [5/8] Security attack regressions (KSA / KSA2 / KSA-TL / Sentinel) =="
python3 -m pytest -q \
  tests/unit/test_openclaw_webhook_retry.py \
  tests/integration/test_payment_intent_expire_admin.py \
  tests/unit/test_sentinel_nonblocking_regressions.py \
  tests/unit/test_security_attack_mitigations.py \
  tests/unit/test_level2_attack_mitigations.py \
  tests/unit/test_trade_launch_security.py \
  tests/unit/test_settlement_cycle_guard.py \
  tests/unit/test_receipt_chronology.py \
  tests/integration/test_triangle_settlement_cycle.py \
  tests/unit/test_ap2_security.py

echo ""
echo "== [6/8] Public acceptance (monorepo + packages + karma-public mirror) =="
bash scripts/run_public_acceptance_tests.sh -q --tb=line

echo ""
echo "== [7/8] Production prelaunch settings (no full on-call gate) =="
bash scripts/production-prelaunch-gate.sh

echo ""
echo "== [8/8] Testnet manifest sample (optional cast) =="
bash scripts/acceptance/verify_testnet_manifest_sample.sh || true

echo ""
echo "========================================"
echo " FULL-CHAIN AUDIT GATE: PASS"
echo " Next: bash scripts/acceptance/testnet_claw_manus_gate.sh (live API + testnet)"
echo "========================================"
