#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${ROOT_DIR}/results"
FORMAT="text"
SKIP_BUNDLE_GEN=0
REPO_ROOT="$(git -C "$ROOT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$REPO_ROOT" ]]; then
  REPO_ROOT="$ROOT_DIR"
fi
DOCS_DIR="${DOCS_DIR:-${REPO_ROOT}/docs}"
OPENAPI_DIR="${OPENAPI_DIR:-${REPO_ROOT}/openapi}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/ci-proof-gates.sh [--format <text|json>] [--skip-bundle-gen]

Description:
  Runs proof/evidence CI gates:
    1) evidence schema compatibility check
    2) support-bundle manifest batch verification with M3.9 policies

Options:
  --format <fmt>     Output format for batch verifier: text (default) or json
  --skip-bundle-gen  Skip support-bundle generation (expects bundles in results/)
  -h, --help         Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --format)
      [[ $# -lt 2 ]] && { echo "Error: --format requires a value"; exit 1; }
      FORMAT="$2"
      if [[ "$FORMAT" != "text" && "$FORMAT" != "json" ]]; then
        echo "Error: --format must be text or json"
        exit 1
      fi
      shift 2
      ;;
    --skip-bundle-gen)
      SKIP_BUNDLE_GEN=1
      shift
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

cd "$ROOT_DIR"
mkdir -p "$RESULTS_DIR"

echo "==> [Gate 1/2] Evidence schema compatibility"
EVIDENCE_INPUT="${DOCS_DIR}/samples/karma-evidence-sample-v1.json"
./scripts/validate-evidence-schema.sh --path "$EVIDENCE_INPUT" --format text

if [[ "$SKIP_BUNDLE_GEN" -eq 0 ]]; then
  echo
  echo "==> Preparing support-bundle sample for proof-index gates"
  ./scripts/support-bundle.sh --port 8790 --operator "ci" --reviewer "ci" --ticket "CI-PROOF-GATE"
fi

echo
echo "==> [Gate 2/2] Proof-index batch policies"
./scripts/verify-proof-index-batch.sh \
  --dir "$RESULTS_DIR" \
  --glob "support-bundle-*.zip" \
  --format "$FORMAT" \
  --strict \
  --max-fail 0 \
  --min-total 1 \
  --require-recent-pass 168

echo
echo "Proof/evidence CI gates passed."
