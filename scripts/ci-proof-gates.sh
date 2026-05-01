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

echo "OK   proof/evidence CI gate passed."
