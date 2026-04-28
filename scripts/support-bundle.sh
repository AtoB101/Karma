#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${ROOT_DIR}/results"
OUT_PATH=""
FROM_ENV=0
PORT=8790
OPERATOR_LABEL="${OPERATOR_LABEL:-bundle-operator}"
REVIEWER_LABEL="${REVIEWER_LABEL:-bundle-reviewer}"
TICKET_ID="${TICKET_ID:-SUPPORT-BUNDLE}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/support-bundle.sh [--from-env] [--port <port>] [--output <zip-path>]

Description:
  Generates a support bundle zip with diagnostics and key artifacts.

Options:
  --from-env         Load .env before generating doctor reports
  --port <port>      Frontend port to inspect in diagnostics (default: 8790)
  --output <path>    Output zip path (default: results/support-bundle-<timestamp>.zip)
  -h, --help         Show this help message
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
      OUT_PATH="$2"
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

mkdir -p "$RESULTS_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -z "$OUT_PATH" ]]; then
  OUT_PATH="${RESULTS_DIR}/support-bundle-${STAMP}.zip"
fi

DOCTOR_ARGS=(--port "$PORT")
if [[ "$FROM_ENV" -eq 1 ]]; then
  DOCTOR_ARGS=(--from-env "${DOCTOR_ARGS[@]}")
fi

"${ROOT_DIR}/scripts/doctor.sh" "${DOCTOR_ARGS[@]}" --format text --output "${RESULTS_DIR}/doctor-report.txt"
"${ROOT_DIR}/scripts/doctor.sh" "${DOCTOR_ARGS[@]}" --format json --output "${RESULTS_DIR}/doctor-report.json"
"${ROOT_DIR}/scripts/proof-sop-checklist.sh" \
  --output "${RESULTS_DIR}/proof-sop-checklist-${STAMP}.md" \
  --operator "${OPERATOR_LABEL}" \
  --reviewer "${REVIEWER_LABEL}" \
  --ticket "${TICKET_ID}"

PRELOG="${RESULTS_DIR}/preflight-last.log"
if ! "${ROOT_DIR}/scripts/preflight.sh" --quiet >"$PRELOG" 2>&1; then
  true
fi

BUNDLE_TMP_DIR="${RESULTS_DIR}/support-bundle-${STAMP}"
rm -rf "$BUNDLE_TMP_DIR"
mkdir -p "$BUNDLE_TMP_DIR"

cp "${RESULTS_DIR}/doctor-report.txt" "$BUNDLE_TMP_DIR/"
cp "${RESULTS_DIR}/doctor-report.json" "$BUNDLE_TMP_DIR/"
cp "${RESULTS_DIR}/proof-sop-checklist-${STAMP}.md" "$BUNDLE_TMP_DIR/"
cp "$PRELOG" "$BUNDLE_TMP_DIR/"

[[ -f "${ROOT_DIR}/results/deploy-v01-eth.json" ]] && cp "${ROOT_DIR}/results/deploy-v01-eth.json" "$BUNDLE_TMP_DIR/"
[[ -f "${ROOT_DIR}/examples/v01-console-config.json" ]] && cp "${ROOT_DIR}/examples/v01-console-config.json" "$BUNDLE_TMP_DIR/"

python3 - "$BUNDLE_TMP_DIR" "$OUT_PATH" <<'PY'
import pathlib
import sys
import zipfile

src_dir = pathlib.Path(sys.argv[1])
out_path = pathlib.Path(sys.argv[2])
out_path.parent.mkdir(parents=True, exist_ok=True)

with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for p in sorted(src_dir.rglob("*")):
        if p.is_file():
            zf.write(p, arcname=p.relative_to(src_dir))
PY

rm -rf "$BUNDLE_TMP_DIR"
echo "Support bundle generated: ${OUT_PATH}"
echo "Share this zip file with maintainers for faster troubleshooting."
