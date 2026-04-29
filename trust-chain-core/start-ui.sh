#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="127.0.0.1"
PORT=""
OPEN_BROWSER=0

usage() {
  cat <<'USAGE'
Usage:
  ./start-ui.sh [--port <n>] [--host <ip>] [--open]

Description:
  Starts Trust-Chain public UI static server.
  - Auto-selects a free port if --port is not provided.
  - Prints entry URLs for all major pages.

Options:
  --port <n>   Use a specific port.
  --host <ip>  Bind host (default: 127.0.0.1).
  --open       Try opening browser automatically.
  -h, --help   Show help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      [[ $# -lt 2 ]] && { echo "Error: --port requires value" >&2; exit 1; }
      PORT="$2"
      shift 2
      ;;
    --host)
      [[ $# -lt 2 ]] && { echo "Error: --host requires value" >&2; exit 1; }
      HOST="$2"
      shift 2
      ;;
    --open)
      OPEN_BROWSER=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$PORT" ]]; then
  PORT="$(python3 - <<'PY'
import socket
for p in [8787,8790,8800,8080,8000,3000,5173]:
    s=socket.socket()
    try:
        s.bind(("127.0.0.1",p))
        print(p)
        s.close()
        break
    except OSError:
        s.close()
else:
    s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()
PY
)"
fi

if [[ ! "$PORT" =~ ^[0-9]+$ ]]; then
  echo "Error: invalid port '$PORT'" >&2
  exit 1
fi

ENTRY="http://${HOST}:${PORT}/index.html"

echo "Starting Trust-Chain public UI..."
echo "Root: ${ROOT_DIR}"
echo "Entry: ${ENTRY}"
echo "Buyer: http://${HOST}:${PORT}/buyer/dashboard/"
echo "Seller: http://${HOST}:${PORT}/seller/dashboard/"
echo "Agent: http://${HOST}:${PORT}/agent/confirm-call/"
echo

if [[ "$OPEN_BROWSER" == "1" ]]; then
  if command -v open >/dev/null 2>&1; then
    open "$ENTRY" || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$ENTRY" || true
  fi
fi

cd "$ROOT_DIR"
exec python3 -m http.server "$PORT" --bind "$HOST"
