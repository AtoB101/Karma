#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Running security baseline guard"

# Block suspicious tracked paths that should not exist in public repo.
blocked_paths_regex='(^|/)(docs-private|scripts-private|examples-private)(/|$)|(^|/)outreach/seller-leads\.csv$|(^|/)security-baseline-report\.md$'

if git ls-files | rg -n "$blocked_paths_regex" >/tmp/security_guard_paths.txt; then
  echo "ERR  blocked private paths detected in tracked files:"
  cat /tmp/security_guard_paths.txt
  exit 1
fi

# Block classic sensitive filename patterns.
blocked_name_regex='(investor|tokenomics-parameters|tokenomics_parameters|seller-leads|private-key|seed-phrase|mnemonic)'
if git ls-files | rg -ni "$blocked_name_regex" >/tmp/security_guard_names.txt; then
  echo "ERR  suspicious sensitive filenames detected:"
  cat /tmp/security_guard_names.txt
  exit 1
fi

# Block obvious insecure auth toggles in tracked files.
if git grep -nE 'allowInsecureAuth[[:space:]]*:[[:space:]]*true' -- . >/tmp/security_guard_insecure_auth.txt; then
  echo "ERR  insecure auth flag detected (allowInsecureAuth:true):"
  cat /tmp/security_guard_insecure_auth.txt
  exit 1
fi

# Block accidental hard-coded credentials with high-confidence token formats.
# NOTE: We intentionally do not block generic 0x{64} literals because Solidity
# code contains legitimate curve/order constants with that shape.
if git grep -nE 'sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}' -- . \
  | rg -v 'DO_NOT_COMMIT|<|replace_with|YOUR_|example|dummy|placeholder' >/tmp/security_guard_literals.txt; then
  echo "ERR  high-confidence hard-coded credentials detected:"
  cat /tmp/security_guard_literals.txt
  exit 1
fi

echo "OK   security baseline guard passed."
