#!/usr/bin/env bash
# Validate deployment-manifest.json before public testnet go-live.
# Thin wrapper around scripts/verify_manifest.py (same flags / env vars).
#
# Default reports template placeholders as warnings and exits 0 so the
# off-chain audit gate is not blocked while remaining fields are filled.
# Set KARMA_MANIFEST_STRICT=1 to fail on any placeholder or invalid field.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 scripts/verify_manifest.py "$@"
