#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/../trust-chain-engine/internal-admin/scripts-private/ci-proof-gates.sh" "$@"
