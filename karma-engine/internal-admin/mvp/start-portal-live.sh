#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${MVP_PORT:-8822}"
HOST="${MVP_HOST:-0.0.0.0}"
STATIC_DIR="${DASHBOARD_STATIC_DIR:-/workspace/karma-core}"

echo "[portal-live] starting Karma portal"
echo "[portal-live] host=${HOST} port=${PORT}"
echo "[portal-live] static=${STATIC_DIR}"

cd "${ROOT_DIR}"
MVP_HOST="${HOST}" MVP_PORT="${PORT}" DASHBOARD_STATIC_DIR="${STATIC_DIR}" node server.js
