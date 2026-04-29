#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  split-release/publish-engine.sh --repo <owner/trust-chain-engine> [--branch <name>] [--remote <name>]

Description:
  Publishes /workspace/trust-chain-engine as an independent private repository history.
  This script initializes a temporary git repo from trust-chain-engine contents and pushes it to target remote.

Example:
  split-release/publish-engine.sh --repo AtoB101/trust-chain-engine --branch main
EOF
}

REPO=""
BRANCH="main"
REMOTE="origin"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --branch)
      BRANCH="${2:-}"
      shift 2
      ;;
    --remote)
      REMOTE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$REPO" ]]; then
  echo "Error: --repo is required" >&2
  usage
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${ROOT_DIR}/trust-chain-engine"
TMP_DIR="${ROOT_DIR}/.tmp-publish-engine"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "Error: source directory not found: $SRC_DIR" >&2
  exit 1
fi

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
cp -R "$SRC_DIR"/. "$TMP_DIR"/

pushd "$TMP_DIR" >/dev/null
git init
git checkout -b "$BRANCH"
git add -A
git commit -m "chore: initialize trust-chain-engine private repository"
git remote add "$REMOTE" "https://github.com/${REPO}.git"
git push -u "$REMOTE" "$BRANCH"
popd >/dev/null

echo "Published trust-chain-engine to https://github.com/${REPO}"
