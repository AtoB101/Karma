#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

FRAMEWORK="openclaw"
WORKSPACE_DIR="."
RUNTIME_URL=""
AGENT_ID=""
API_KEY=""
OVERWRITE="false"
SKIP_RUNTIME_CHECK="true"
START_COMPOSE="false"
COMPOSE_FILE=""

usage() {
  cat <<'EOF'
Usage:
  bash scripts/ecosystem/quickstart.sh [options]

Options:
  --framework <openclaw|openmanus>   Target ecosystem (default: openclaw)
  --workspace-dir <path>             Workspace to generate scaffold in (default: .)
  --runtime-url <url>                Override KARMA runtime URL
  --agent-id <id>                    Override KARMA agent id
  --api-key <key>                    Override KARMA api key
  --overwrite                        Overwrite existing scaffold files
  --skip-runtime-check               Skip runtime health check (default)
  --no-skip-runtime-check            Enable runtime health check
  --start-compose                    Start ecosystem docker compose after bootstrap
  --no-compose                       Do not start docker compose (default)
  --compose-file <path>              Override compose file path
  -h, --help                         Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --framework)
      FRAMEWORK="${2:-}"
      shift 2
      ;;
    --workspace-dir)
      WORKSPACE_DIR="${2:-}"
      shift 2
      ;;
    --runtime-url)
      RUNTIME_URL="${2:-}"
      shift 2
      ;;
    --agent-id)
      AGENT_ID="${2:-}"
      shift 2
      ;;
    --api-key)
      API_KEY="${2:-}"
      shift 2
      ;;
    --overwrite)
      OVERWRITE="true"
      shift
      ;;
    --skip-runtime-check)
      SKIP_RUNTIME_CHECK="true"
      shift
      ;;
    --no-skip-runtime-check)
      SKIP_RUNTIME_CHECK="false"
      shift
      ;;
    --start-compose)
      START_COMPOSE="true"
      shift
      ;;
    --no-compose)
      START_COMPOSE="false"
      shift
      ;;
    --compose-file)
      COMPOSE_FILE="${2:-}"
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

if [[ "${FRAMEWORK}" != "openclaw" && "${FRAMEWORK}" != "openmanus" ]]; then
  echo "Unsupported framework: ${FRAMEWORK}"
  exit 1
fi

mkdir -p "${WORKSPACE_DIR}"
WORKSPACE_DIR="$(cd "${WORKSPACE_DIR}" && pwd)"

run_karma_ecosystem() {
  if command -v karma-ecosystem >/dev/null 2>&1; then
    karma-ecosystem "$@"
    return
  fi
  python3 -m sdk.ecosystem.cli "$@"
}

ARGS=(
  --framework "${FRAMEWORK}"
  --workspace-dir "${WORKSPACE_DIR}"
)

if [[ -n "${RUNTIME_URL}" ]]; then
  ARGS+=(--runtime-url "${RUNTIME_URL}")
fi
if [[ -n "${AGENT_ID}" ]]; then
  ARGS+=(--agent-id "${AGENT_ID}")
fi
if [[ -n "${API_KEY}" ]]; then
  ARGS+=(--api-key "${API_KEY}")
fi
if [[ "${OVERWRITE}" == "true" ]]; then
  ARGS+=(--overwrite)
fi
if [[ "${SKIP_RUNTIME_CHECK}" == "true" ]]; then
  ARGS+=(--skip-runtime-check)
fi

cd "${REPO_ROOT}"
run_karma_ecosystem "${ARGS[@]}" bootstrap

bash "${WORKSPACE_DIR}/scripts/karma-ecosystem-inject-env.sh" "${WORKSPACE_DIR}"

if [[ "${START_COMPOSE}" == "true" ]]; then
  if [[ -z "${COMPOSE_FILE}" ]]; then
    COMPOSE_FILE="${WORKSPACE_DIR}/deploy/karma-ecosystem/docker-compose.${FRAMEWORK}.yml"
  fi
  if [[ ! -f "${COMPOSE_FILE}" ]]; then
    echo "Compose file not found: ${COMPOSE_FILE}"
    exit 1
  fi
  docker compose -f "${COMPOSE_FILE}" up -d
fi

echo "Karma ecosystem quickstart completed."
echo "Framework: ${FRAMEWORK}"
echo "Workspace: ${WORKSPACE_DIR}"
echo "Next: edit ${WORKSPACE_DIR}/.env.karma with real credentials."
