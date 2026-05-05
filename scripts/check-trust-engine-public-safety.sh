#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Trust Engine public safety guard"

declare -a blocked_keywords=(
  "exact weight table"
  "anti-cheat threshold constants"
  "evidence weight matrix"
  "arbitration tie-break constants"
)

failed=0
for keyword in "${blocked_keywords[@]}"; do
  if rg -n -i \
    --glob '!results/**' \
    --glob '!*node_modules/**' \
    --glob '!scripts/check-trust-engine-public-safety.sh' \
    --glob '!docs/TRUST_ENGINE_V1_PUBLIC_SCHEMA.md' \
    "$keyword" . >/tmp/trust_engine_blocked_keyword.txt; then
    echo "ERR  blocked private leakage keyword detected: $keyword"
    cat /tmp/trust_engine_blocked_keyword.txt
    failed=1
  fi
done

if [[ "$failed" -ne 0 ]]; then
  exit 1
fi

echo "OK   trust-engine public safety guard passed."
