#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR_DEFAULT="${ROOT_DIR}/results/karma2-sync-package"

out_dir="$OUT_DIR_DEFAULT"
core_tag="${CORE_TAG:-}"
core_commit="${CORE_COMMIT:-}"
core_repo="${CORE_REPO:-AtoB101/Karma}"
private_repo="${PRIVATE_REPO:-AtoB101/Karma2}"

usage() {
  cat <<'EOF'
Usage:
  ./split-release/prepare-karma2-sync-package.sh [--out-dir <dir>] [--core-tag <tag>] [--core-commit <sha>]

Description:
  Build a deterministic sync package for Karma2 to keep interface/env/deployment linkage
  aligned with the latest Karma core baseline.

Outputs:
  <out-dir>/SYNC_METADATA.env
  <out-dir>/openapi/karma-v1.yaml
  <out-dir>/templates/CORE_VERSION.lock.example
  <out-dir>/templates/deployment-manifest.json.example
  <out-dir>/templates/verify-manifest.sh
  <out-dir>/templates/README.md
  <out-dir>/contracts/interfaces/*
  <out-dir>/internal-admin/core-devops/.env.example.template
  <out-dir>/README.md
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out-dir)
      out_dir="$2"
      shift 2
      ;;
    --core-tag)
      core_tag="$2"
      shift 2
      ;;
    --core-commit)
      core_commit="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERR  unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$core_commit" ]]; then
  core_commit="$(git -C "$ROOT_DIR" rev-parse HEAD)"
fi

if [[ -z "$core_tag" ]]; then
  core_tag="core-unreleased-${core_commit:0:7}"
fi

rm -rf "$out_dir"
mkdir -p "$out_dir/openapi" "$out_dir/templates/workflows" "$out_dir/contracts/interfaces" "$out_dir/internal-admin/core-devops"

cp "$ROOT_DIR/openapi/karma-v1.yaml" "$out_dir/openapi/karma-v1.yaml"
cp "$ROOT_DIR/split-release/templates/karma2/CORE_VERSION.lock.example" "$out_dir/templates/CORE_VERSION.lock.example"
cp "$ROOT_DIR/split-release/templates/karma2/deployment-manifest.json.example" "$out_dir/templates/deployment-manifest.json.example"
cp "$ROOT_DIR/split-release/templates/karma2/verify-manifest.sh" "$out_dir/templates/verify-manifest.sh"
cp "$ROOT_DIR/split-release/templates/karma2/README.md" "$out_dir/templates/README.md"
cp "$ROOT_DIR/split-release/templates/karma2/workflows/lockstep-sync-check.yml" "$out_dir/templates/workflows/lockstep-sync-check.yml"
cp "$ROOT_DIR"/karma-core/contracts/interfaces/*.sol "$out_dir/contracts/interfaces/"
cp "$ROOT_DIR/karma-engine/internal-admin/core-devops/.env.example.template" "$out_dir/internal-admin/core-devops/.env.example.template"

cat > "$out_dir/SYNC_METADATA.env" <<EOF
CORE_REPO=${core_repo}
CORE_TAG=${core_tag}
CORE_COMMIT=${core_commit}
PRIVATE_REPO=${private_repo}
GENERATED_AT_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

cat > "$out_dir/README.md" <<'EOF'
# Karma2 Sync Package

This package is generated from `Karma` and is intended to be imported into `Karma2`.

## Purpose

Keep the private repository aligned with the public core baseline:
- API contract (`openapi/karma-v1.yaml`)
- Solidity interface surface (`contracts/interfaces/*.sol`)
- deployment/environment template (`internal-admin/core-devops/.env.example.template`)
- cross-repo lock + manifest templates
- CI drift guard workflow template

## Import steps in Karma2

1. Copy this package into the Karma2 repository root.
2. Update:
   - `templates/CORE_VERSION.lock.example` -> `CORE_VERSION.lock`
   - `templates/deployment-manifest.json.example` -> `deployment-manifest.json`
3. Fill lock + manifest with actual release tag, commit SHA, and deployed addresses.
4. Validate alignment:
   - `bash templates/verify-manifest.sh --manifest deployment-manifest.json --lock CORE_VERSION.lock`
5. Install drift guard workflow:
   - `mkdir -p .github/workflows`
   - `cp templates/workflows/lockstep-sync-check.yml .github/workflows/lockstep-sync-check.yml`
6. Commit lock/manifest/workflow in Karma2 and run private CI + smoke tests.
EOF

chmod +x "$out_dir/templates/verify-manifest.sh"

echo "OK   Karma2 sync package generated at: $out_dir"
