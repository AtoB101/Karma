#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODE="range"
TARGET_RANGE="${1:-HEAD~1..HEAD}"
if [[ "${TARGET_RANGE}" == "--range" ]]; then
  TARGET_RANGE="${2:-HEAD~1..HEAD}"
fi
if [[ "${1:-}" == "--staged" ]]; then
  MODE="staged"
fi

if [[ "$MODE" == "staged" ]]; then
  echo "[visibility-guard] scanning staged diff"
  changed_files="$(git diff --name-only --cached || true)"
else
  echo "[visibility-guard] scanning range: ${TARGET_RANGE}"
  changed_files="$(git diff --name-only "${TARGET_RANGE}" || true)"
fi
if [[ -z "${changed_files}" ]]; then
  echo "[visibility-guard] no changed files"
  exit 0
fi

fail=0

# 1) Private paths should not include obvious secret material in text files.
private_text_patterns='(PRIVATE KEY|BEGIN (RSA|EC|OPENSSH) PRIVATE KEY|x-access-token:|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})'
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  [[ ! -f "$f" ]] && continue
  case "$f" in
    trust-chain-engine/*|trust-chain-engine/internal-admin/*)
      if file "$f" | rg -q "text"; then
        if rg -n "$private_text_patterns" "$f" >/dev/null; then
          echo "[visibility-guard][FAIL] suspected secret in private path file: $f"
          fail=1
        fi
      fi
      ;;
  esac
done <<< "$changed_files"

# 2) Public area should not reference private-only docs/scripts directly.
public_ref_forbidden='trust-chain-engine/internal-admin/docs-private|trust-chain-engine/internal-admin/scripts-private'
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  [[ ! -f "$f" ]] && continue
  case "$f" in
    trust-chain-core/*|docs/*|openapi/*|README.md|SECURITY.md)
      if file "$f" | rg -q "text"; then
        if rg -n "$public_ref_forbidden" "$f" >/dev/null; then
          echo "[visibility-guard][FAIL] public-facing file references private path: $f"
          fail=1
        fi
      fi
      ;;
  esac
done <<< "$changed_files"

# 3) Ensure naming and API conventions in changed files.
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  [[ ! -f "$f" ]] && continue
  case "$f" in
    *.md|*.yml|*.yaml|*.json|*.js|*.ts|*.html|*.sh|README.md|SECURITY.md)
      if rg -n "Trust-Chain|TrustChain" "$f" >/dev/null; then
        echo "[visibility-guard][FAIL] legacy naming found: $f"
        fail=1
      fi
      if rg -n "trustchain-v1\\.yaml|trustchain-evidence-sample-v1\\.json" "$f" >/dev/null; then
        echo "[visibility-guard][FAIL] legacy named artifact reference found: $f"
        fail=1
      fi
      ;;
  esac
done <<< "$changed_files"

if [[ "$fail" -ne 0 ]]; then
  echo "[visibility-guard] FAILED"
  exit 2
fi

echo "[visibility-guard] PASS"
