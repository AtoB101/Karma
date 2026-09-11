#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Testing trust-engine public schema presence"

python3 - <<'PY'
from pathlib import Path
import sys

spec = Path("openapi/karma-v1.yaml").read_text()
required_tokens = [
    "caller_authorization_signature",
    "provider_execution_signature",
    "request_hash",
    "response_hash",
    "execution_trace_hash",
    "dispute_status",
    "settlement_status",
]
missing = [t for t in required_tokens if t not in spec]
if missing:
    print("ERR  missing required trust-engine public schema fields:")
    for token in missing:
        print(f" - {token}")
    sys.exit(1)

print("OK   trust-engine public schema fields are present")
PY
