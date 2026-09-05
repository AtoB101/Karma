#!/usr/bin/env bash
# Contract size gate: fail the build if any contract's runtime code exceeds
# the EIP-170 limit (24576 bytes). This caught the KarmaBilateral oversize
# regression that made the core settlement contract undeployable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Contract size gate (EIP-170)"
out="$(forge build --sizes 2>&1 || true)"
if echo "$out" | grep -q "exceed the runtime size limit"; then
  echo "ERR  a contract exceeds the EIP-170 runtime size limit (24576 bytes)"
  echo "$out" | grep -E "exceed|Runtime Size" || true
  exit 1
fi
echo "OK   all contracts under EIP-170"
