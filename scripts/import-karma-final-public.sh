#!/usr/bin/env bash
# Import karma-public/ from karma-final.zip into this repo on branch feat/karma-runtime,
# commit, and push to origin. Does NOT touch karma-private/.
#
# Usage:
#   ./scripts/import-karma-final-public.sh [path/to/karma-final.zip]
#
# Env:
#   KARMA_IMPORT_BRANCH=feat/karma-runtime  (default)
#   KARMA_IMPORT_RSYNC_DELETE=1             if karma-public is a FULL tree replacement —
#                                           rsync uses --delete (dangerous if zip is partial)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ZIP="${1:-$ROOT/karma-final.zip}"

if [[ ! -f "$ZIP" ]]; then
  echo "error: archive not found: $ZIP"
  echo "Place karma-final.zip at repo root ($ROOT), or pass the path as the first argument."
  exit 1
fi

command -v unzip >/dev/null || {
  echo "error: unzip not installed"
  exit 1
}

TMP="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "Extracting → $TMP"
unzip -q "$ZIP" -d "$TMP"

PUBLIC=""
if [[ -d "$TMP/karma-public" ]]; then
  PUBLIC="$TMP/karma-public"
elif [[ -d "$TMP/karma-final/karma-public" ]]; then
  PUBLIC="$TMP/karma-final/karma-public"
else
  echo "error: could not find karma-public/ inside zip."
  echo "Expected: karma-public/ or karma-final/karma-public/"
  find "$TMP" -maxdepth 3 -type d -print || true
  exit 1
fi

TARGET_BRANCH="${KARMA_IMPORT_BRANCH:-feat/karma-runtime}"

git fetch origin 2>/dev/null || true

if git rev-parse --verify "$TARGET_BRANCH" >/dev/null 2>&1; then
  git checkout "$TARGET_BRANCH"
elif git rev-parse --verify "origin/$TARGET_BRANCH" >/dev/null 2>&1; then
  git checkout -B "$TARGET_BRANCH" "origin/$TARGET_BRANCH"
else
  BASE="main"
  if git rev-parse --verify "origin/main" >/dev/null 2>&1; then
    BASE="origin/main"
  fi
  git rev-parse --verify "$BASE" >/dev/null || {
    echo "error: cannot resolve base branch (tried origin/main / main)."
    exit 1
  }
  git checkout -B "$TARGET_BRANCH" "$BASE"
fi

DELETE_FLAG=()
if [[ "${KARMA_IMPORT_RSYNC_DELETE:-}" == "1" ]]; then
  DELETE_FLAG+=(--delete)
  echo "warning: rsync --delete enabled; files absent from karma-public will be REMOVED from repo."
fi

echo "Staging copy from $PUBLIC → $ROOT"
rsync -a "${DELETE_FLAG[@]}" \
  --exclude ".git/" \
  --exclude ".cursor/" \
  --exclude ".DS_Store" \
  "$PUBLIC"/ "$ROOT"/

git add -A
if git diff --cached --quiet; then
  echo "nothing to commit (already matches karma-public snapshot)."
else
  git commit -m "feat: import karma-public from karma-final.zip (runtime bundle)

Imported via scripts/import-karma-final-public.sh
Excluded: karma-private (private Karma2 subtree)."
fi

git push -u origin "$TARGET_BRANCH"

echo "OK — pushed branch: $TARGET_BRANCH"
echo "Confirm remote targets AtoB101/Karma:"
git remote -v
