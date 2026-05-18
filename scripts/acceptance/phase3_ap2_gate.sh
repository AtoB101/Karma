#!/usr/bin/env bash
# Phase 3 AP2 / PaymentIntent acceptance gate
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== Phase 3 AP2 gate =="
python3 -m pytest -q \
  tests/unit/test_ap2_adapter.py \
  tests/unit/test_evidence_export.py \
  tests/unit/test_human_not_present_policy.py \
  tests/integration/test_phase3_payment_intent.py

echo "Phase 3 gate: PASS"
