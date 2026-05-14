#!/usr/bin/env bash
# Public acceptance gate (no real testnet RPC):
#   Phase 1 — monorepo root: tests/ + OpenManus + OpenClaw packages
#   Phase 2 — karma-final/karma-public snapshot in its own cwd (avoids sys.path clashes with root core/api)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== Acceptance phase 1: monorepo (tests + packages) =="
python3 -m pytest \
  tests/ \
  packages/karma-openmanus/tests \
  packages/karma-openclaw/tests \
  "$@"

echo "== Acceptance phase 2: karma-final/karma-public (isolated cwd) =="
cd "$ROOT/karma-final/karma-public"
python3 -m pytest tests/ "$@"
