#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example and fill values first."
  exit 1
fi

export $(grep -v '^#' .env | xargs)

echo "Starting Karma P0 BTC paid API demo..."
echo "Demo URL: http://127.0.0.1:${MVP_PORT:-8822}/"
echo "API health: http://127.0.0.1:${MVP_PORT:-8822}/api/health"
echo

node server.js
