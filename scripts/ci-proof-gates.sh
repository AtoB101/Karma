#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Proof / evidence CI gate (public-safe)"

# 1) Enforce public/private leakage baseline first.
./scripts/security-baseline-guard.sh

# 2) Verify critical artifacts and specs expected in this public repo.
required_files=(
  "openapi/karma-v1.yaml"
  "SECURITY.md"
  "scripts/security-baseline-guard.sh"
  "docs/TRUST_ENGINE_V1_PUBLIC_SCHEMA.md"
  "scripts/check-trust-engine-public-safety.sh"
)

missing=0
for f in "${required_files[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "ERR  missing required file: $f"
    missing=1
  else
    echo "OK   found required file: $f"
  fi
done

if [[ "$missing" -ne 0 ]]; then
  echo "ERR  proof/evidence gate failed due to missing required files"
  exit 1
fi

# 3) Ensure trust-engine public surface exists while private internals stay private.
./scripts/check-trust-engine-public-safety.sh

echo "OK   proof/evidence CI gate passed."
