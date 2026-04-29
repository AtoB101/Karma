#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./split-release/publish-core.sh --repo-url <url> [--branch main] [--workdir .publish-core]

Description:
  Publish / refresh karma-core as an independent git repository.
  This script creates a clean git repo from karma-core contents and pushes it.

Examples:
  ./split-release/publish-core.sh --repo-url git@github.com:org/karma-core.git
  ./split-release/publish-core.sh --repo-url https://github.com/org/karma-core.git --branch main
EOF
}

REPO_URL=""
BRANCH="main"
WORKDIR=".publish-core"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --branch)
      BRANCH="${2:-}"
      shift 2
      ;;
    --workdir)
      WORKDIR="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$REPO_URL" ]]; then
  echo "Error: --repo-url is required" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$ROOT_DIR/karma-core"
TMP_DIR="$ROOT_DIR/$WORKDIR"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "Error: source directory not found: $SRC_DIR" >&2
  exit 1
fi

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
cp -R "$SRC_DIR"/. "$TMP_DIR"/

cd "$TMP_DIR"
rm -rf .git
git init
git checkout -b "$BRANCH"
git add -A
git commit -m "chore: initialize karma-core public repository"
git remote add origin "$REPO_URL"
git push -u origin "$BRANCH"

echo "Published karma-core to $REPO_URL (branch: $BRANCH)"
