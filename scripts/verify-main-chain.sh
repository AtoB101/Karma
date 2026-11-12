#!/usr/bin/env bash
# Main-chain cleanliness gate: fails if non-core artifacts leak back into the
# main chain, or if preserved areas are not properly separated. Nothing is
# deleted by this gate; it only verifies the classification from docs/MAIN_CHAIN_MAP.md.
set -euo pipefail

cd "$(dirname "$0")/.."

fail=0
say() { printf '%s\n' "$*"; }

# 1) Main chain must not import from the holding areas.
if rg -n '^\s*(from|import)\s+(legacy|experimental)\b' \
     --glob '*.py' --glob '!legacy/**' --glob '!experimental/**' \
     api core services sdk packages evidence_runtime worker agents config db 2>/dev/null; then
  say "ERR main-chain python imports from legacy/ or experimental/"
  fail=1
else
  say "ok   no python imports from legacy/ or experimental/"
fi

# 2) No scratch/probe/backup files on the main chain (dunders are fine).
scratch_hits="$(find . -path ./.git -prune -o -path ./legacy -prune -o -path ./scratch -prune -o \
  -type f \( -name '__*.py' -o -name '_*.py' -o -name '*.bak' \) \
  ! -name '__init__.py' ! -name '__main__.py' -print 2>/dev/null)"
if [[ -n "$scratch_hits" ]]; then
  say "ERR scratch/probe files on main chain:"; printf '%s\n' "$scratch_hits"
  fail=1
else
  say "ok   no scratch/probe files on main chain"
fi

# 3) decentralized_verifier must live only under experimental/.
if [[ -e decentralized_verifier ]]; then
  say "ERR decentralized_verifier present at repo root (should be experimental/decentralized_verifier)"
  fail=1
else
  say "ok   decentralized_verifier is separated under experimental/"
fi

# 4) scratch/ and the local forge lib clone must be git-ignored.
for p in scratch/ karma-core/contracts/lib/; do
  if git check-ignore -q "$p" 2>/dev/null; then
    say "ok   $p is git-ignored"
  else
    say "ERR $p is not git-ignored"
    fail=1
  fi
done

# 5) legacy/ must NOT be git-ignored: it must remain committable for later merge.
if grep -qE '^/?legacy/?[[:space:]]*$' .gitignore 2>/dev/null; then
  say "ERR legacy/ is git-ignored; it must stay committed for later merge"
  fail=1
else
  say "ok   legacy/ is preserved and committable"
fi

if [[ "$fail" -ne 0 ]]; then
  say "main-chain gate failed"
  exit 1
fi
say "OK   main-chain gate passed"
