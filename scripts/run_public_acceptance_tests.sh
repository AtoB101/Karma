#!/usr/bin/env bash
# Public acceptance gate (no real testnet RPC): monorepo root tests + packages.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== Acceptance: monorepo (tests + packages) =="
python3 -m pytest \
  tests/ \
  packages/karma-openmanus/tests \
  packages/karma-openclaw/tests \
  "$@"
