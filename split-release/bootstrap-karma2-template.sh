#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-$ROOT_DIR/results/karma2-template}"

mkdir -p "$TARGET_DIR"
mkdir -p "$TARGET_DIR/deploy"
mkdir -p "$TARGET_DIR/deploy/templates"

cp "$ROOT_DIR/split-release/templates/karma2/CORE_VERSION.lock.example" \
  "$TARGET_DIR/deploy/CORE_VERSION.lock"
cp "$ROOT_DIR/split-release/templates/karma2/deployment-manifest.json.example" \
  "$TARGET_DIR/deploy/deployment-manifest.json"
cp "$ROOT_DIR/split-release/templates/karma2/README.md" \
  "$TARGET_DIR/deploy/README.md"
cp "$ROOT_DIR/split-release/verify-cross-repo-manifest.sh" \
  "$TARGET_DIR/deploy/verify-cross-repo-manifest.sh"

chmod +x "$TARGET_DIR/deploy/verify-cross-repo-manifest.sh"

echo "OK   Karma2 template generated at: $TARGET_DIR/deploy"
