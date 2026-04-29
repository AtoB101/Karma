#!/usr/bin/env bash
set -euo pipefail

exec ./trust-chain-engine/internal-admin/scripts-private/slither-gate.sh "$@"
