#!/usr/bin/env bash
# Runnable real-commerce closed-loop test (no Docker).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export APP_ENV="${APP_ENV:-test}"
export INTENT_FULFILL_DISABLE_DEMO_MERCHANTS="${INTENT_FULFILL_DISABLE_DEMO_MERCHANTS:-1}"
export A2A_REGISTRY_URL="${A2A_REGISTRY_URL:-}"
echo "== Karma real-commerce scenario loop =="
python3 scripts/acceptance/real_commerce_scenario_loop.py "$@"
