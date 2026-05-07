#!/usr/bin/env bash
# Generate apps/agent-service-guard/frontend/public-config.json from the environment.
#
# Usage:
#   export WALLETCONNECT_PROJECT_ID="your_walletconnect_cloud_project_id"
#   ./scripts/deploy/write-agent-guard-public-config.sh
#
# Optional first argument: output file path (default: frontend/public-config.json under agent-service-guard).

set -euo pipefail

umask 077

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$ROOT/apps/agent-service-guard/frontend/public-config.json}"
export WRITE_PATH="$OUT"

if [[ -z "${WALLETCONNECT_PROJECT_ID:-}" ]]; then
  echo "error: WALLETCONNECT_PROJECT_ID is not set" >&2
  exit 1
fi

python3 <<'PY'
import json, os

path = os.environ["WRITE_PATH"]
val = os.environ.get("WALLETCONNECT_PROJECT_ID", "").strip()
os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump({"walletConnectProjectId": val}, f, indent=2)
    f.write("\n")
PY

chmod 600 "$OUT" 2>/dev/null || true

echo "wrote $OUT (mode 600)"
