#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
REPORT_PATH="${ROOT_DIR}/results/doctor-report.txt"
PORT="${PORT:-8790}"
FROM_ENV=0
FORMAT="text"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/doctor.sh [--from-env] [--port <port>] [--output <path>] [--format <text|json>]

Description:
  Collects environment diagnostics for troubleshooting setup issues.

Options:
  --from-env      Load variables from .env in repository root
  --port <port>   Check whether this frontend port is already in use (default: 8790)
  --output <path> Output report file path (default: results/doctor-report.txt)
  --format <fmt>  Report format: text (default) or json
  -h, --help      Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-env)
      FROM_ENV=1
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
    --output)
      if [[ $# -lt 2 ]]; then
        echo "Error: --output requires a value"
        exit 1
      fi
      REPORT_PATH="$2"
      shift 2
      ;;
    --format)
      if [[ $# -lt 2 ]]; then
        echo "Error: --format requires a value"
        exit 1
      fi
      FORMAT="$2"
      if [[ "$FORMAT" != "text" && "$FORMAT" != "json" ]]; then
        echo "Error: --format must be 'text' or 'json'"
        exit 1
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ "$REPORT_PATH" == "${ROOT_DIR}/results/doctor-report.txt" && "$FORMAT" == "json" ]]; then
  REPORT_PATH="${ROOT_DIR}/results/doctor-report.json"
fi

if [[ "$FROM_ENV" -eq 1 ]]; then
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "Missing .env file at ${ENV_FILE}"
    exit 1
  fi
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

mkdir -p "$(dirname "$REPORT_PATH")"

has_cmd() { command -v "$1" >/dev/null 2>&1; }
yes_no() { [[ "$1" -eq 0 ]] && echo "yes" || echo "no"; }
masked() {
  local value="${1:-}"
  if [[ -z "$value" ]]; then
    echo "unset"
  else
    echo "set(len=${#value})"
  fi
}

forge_ok=1; cast_ok=1; python_ok=1; tmux_ok=1
has_cmd forge && forge_ok=0
has_cmd cast && cast_ok=0
has_cmd python3 && python_ok=0
has_cmd tmux && tmux_ok=0

env_rpc="${ETH_RPC_URL:-}"
env_pk="${DEPLOYER_PRIVATE_KEY:-}"
env_admin="${ADMIN_ADDRESS:-}"
env_token="${TOKEN_ADDRESS:-}"
env_payee="${PAYEE_ADDRESS:-}"

preflight_result="pass"
if ! "$ROOT_DIR/scripts/preflight.sh" $([[ "$FROM_ENV" -eq 1 ]] && echo "--from-env") --quiet >/tmp/trustchain-preflight.log 2>&1; then
  preflight_result="fail"
fi

port_status="unknown"
if has_cmd ss; then
  if ss -ltn | rg -q ":${PORT}\\b"; then
    port_status="in-use"
  else
    port_status="free"
  fi
fi

config_exists="no"
[[ -f "${ROOT_DIR}/examples/v01-console-config.json" ]] && config_exists="yes"
deploy_exists="no"
[[ -f "${ROOT_DIR}/results/deploy-v01-eth.json" ]] && deploy_exists="yes"

{
  if [[ "$FORMAT" == "json" ]]; then
    cat <<EOF
{
  "generatedAt": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "repoRoot": "${ROOT_DIR}",
  "gitBranch": "$(git -C "$ROOT_DIR" branch --show-current 2>/dev/null || echo unknown)",
  "binaries": {
    "forge": "$(yes_no "$forge_ok")",
    "cast": "$(yes_no "$cast_ok")",
    "python3": "$(yes_no "$python_ok")",
    "tmux": "$(yes_no "$tmux_ok")"
  },
  "environment": {
    "ETH_RPC_URL": "$(masked "$env_rpc")",
    "DEPLOYER_PRIVATE_KEY": "$(masked "$env_pk")",
    "ADMIN_ADDRESS": "$(masked "$env_admin")",
    "TOKEN_ADDRESS": "$(masked "$env_token")",
    "PAYEE_ADDRESS": "$(masked "$env_payee")"
  },
  "files": {
    "examples/v01-console-config.json": "${config_exists}",
    "results/deploy-v01-eth.json": "${deploy_exists}"
  },
  "checks": {
    "preflight": "${preflight_result}",
    "frontendPort": {
      "port": "${PORT}",
      "status": "${port_status}"
    }
  },
  "tips": [
    "Run: make preflight",
    "Run: make quickstart",
    "If stale UI: hard refresh browser"
  ]
}
EOF
  else
    echo "=== TrustChain Doctor Report ==="
    echo "generated_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "repo_root: ${ROOT_DIR}"
    echo "git_branch: $(git -C "$ROOT_DIR" branch --show-current 2>/dev/null || echo unknown)"
    echo
    echo "[binaries]"
    echo "forge: $(yes_no "$forge_ok")"
    echo "cast: $(yes_no "$cast_ok")"
    echo "python3: $(yes_no "$python_ok")"
    echo "tmux: $(yes_no "$tmux_ok")"
    echo
    echo "[environment]"
    echo "ETH_RPC_URL: $(masked "$env_rpc")"
    echo "DEPLOYER_PRIVATE_KEY: $(masked "$env_pk")"
    echo "ADMIN_ADDRESS: $(masked "$env_admin")"
    echo "TOKEN_ADDRESS: $(masked "$env_token")"
    echo "PAYEE_ADDRESS: $(masked "$env_payee")"
    echo
    echo "[files]"
    echo "examples/v01-console-config.json: ${config_exists}"
    echo "results/deploy-v01-eth.json: ${deploy_exists}"
    echo
    echo "[checks]"
    echo "preflight: ${preflight_result}"
    echo "frontend_port_${PORT}: ${port_status}"
    echo
    echo "[tips]"
    echo "- Run: make preflight"
    echo "- Run: make quickstart"
    echo "- If stale UI: hard refresh browser"
  fi
} > "$REPORT_PATH"

echo "Doctor report generated: ${REPORT_PATH}"
echo "Share this file when asking for support."
