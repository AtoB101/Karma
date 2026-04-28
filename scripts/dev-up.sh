#!/usr/bin/env bash
set -euo pipefail

show_help() {
  cat <<'EOF'
Usage:
  ./scripts/dev-up.sh [--from-env] [--port <port>] [--skip-deploy]

Description:
  Run preflight checks, optionally deploy contracts, start frontend server,
  and print the final URL.

Flags:
  --from-env     Load variables from .env (if file exists)
  --port <port>  Frontend port (default: 8790)
  --skip-deploy  Skip deploy-v01-eth.sh and only start frontend
  --help         Show this help
EOF
}

PORT=8790
LOAD_ENV=0
SKIP_DEPLOY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-env)
      LOAD_ENV=1
      shift
      ;;
    --port)
      if [[ $# -lt 2 ]]; then
        echo "Error: --port requires a value"
        exit 1
      fi
      PORT="$2"
      shift 2
      ;;
    --skip-deploy)
      SKIP_DEPLOY=1
      shift
      ;;
    --help|-h)
      show_help
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      show_help
      exit 1
      ;;
  esac
done

if [[ "$LOAD_ENV" == "1" ]]; then
  if [[ ! -f .env ]]; then
    echo "Error: .env not found in repository root. Create it from .env.example."
    exit 1
  fi
  # shellcheck disable=SC1091
  set -a; source .env; set +a
  echo "Loaded .env"
fi

./scripts/preflight.sh

if [[ "$SKIP_DEPLOY" == "0" ]]; then
  echo
  echo "==> Running deploy script"
  ./scripts/deploy-v01-eth.sh
fi

echo
echo "==> Starting frontend server on port ${PORT}"
SESSION_NAME="frontend-console-server-${PORT}"
tmux -f /exec-daemon/tmux.portal.conf has-session -t "=${SESSION_NAME}" 2>/dev/null || \
  tmux -f /exec-daemon/tmux.portal.conf new-session -d -s "${SESSION_NAME}" -c "$PWD" -- "${SHELL:-bash}" -l
tmux -f /exec-daemon/tmux.portal.conf send-keys -t "${SESSION_NAME}:0.0" C-c
tmux -f /exec-daemon/tmux.portal.conf send-keys -t "${SESSION_NAME}:0.0" "python3 -m http.server ${PORT}" C-m

sleep 1
URL="http://127.0.0.1:${PORT}/examples/v01-metamask-settlement.html?ts=$(date +%s)"

echo
echo "Done."
echo "Frontend URL: ${URL}"
echo "If browser still shows old content, hard refresh: Ctrl+F5 (Cmd+Shift+R on Mac)."
