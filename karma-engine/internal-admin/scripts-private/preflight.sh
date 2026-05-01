#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTERNAL_ADMIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

exec "${INTERNAL_ADMIN_DIR}/core-devops/scripts/preflight.sh" "$@"
