#!/usr/bin/env bash
set -euo pipefail

exec ./karma-engine/internal-admin/scripts-private/slither-gate.sh "$@"
