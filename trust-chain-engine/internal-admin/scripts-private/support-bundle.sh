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
  ./scripts/support-bundle.sh [--from-env] [--port <port>] [--output <zip-path>] [--operator <name>] [--reviewer <name>] [--ticket <id>]

Description:
  Generates a support bundle zip with diagnostics and key artifacts.

Options:
  --from-env         Load .env before generating doctor reports
  --port <port>      Frontend port to inspect in diagnostics (default: 8790)
  --output <path>    Output zip path (default: results/support-bundle-<timestamp>.zip)
  --operator <name>  Operator label for SOP checklist metadata
  --reviewer <name>  Reviewer label for SOP checklist metadata
  --ticket <id>      Ticket/case ID for SOP checklist metadata
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
    --operator)
      if [[ $# -lt 2 ]]; then
        echo "Error: --operator requires a value"
        exit 1
      fi
      OPERATOR_LABEL="$2"
      shift 2
      ;;
    --reviewer)
      if [[ $# -lt 2 ]]; then
        echo "Error: --reviewer requires a value"
        exit 1
      fi
      REVIEWER_LABEL="$2"
      shift 2
      ;;
    --ticket)
      if [[ $# -lt 2 ]]; then
        echo "Error: --ticket requires a value"
        exit 1
      fi
      TICKET_ID="$2"
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
cp "${RESULTS_DIR}/proof-sop-checklist-${STAMP}.md" "$BUNDLE_TMP_DIR/proof-sop-checklist.md"
cp "$PRELOG" "$BUNDLE_TMP_DIR/"

[[ -f "${ROOT_DIR}/results/deploy-v01-eth.json" ]] && cp "${ROOT_DIR}/results/deploy-v01-eth.json" "$BUNDLE_TMP_DIR/"
[[ -f "${ROOT_DIR}/examples/v01-console-config.json" ]] && cp "${ROOT_DIR}/examples/v01-console-config.json" "$BUNDLE_TMP_DIR/"

MANIFEST_DIGEST="$(python3 - "$BUNDLE_TMP_DIR" "$STAMP" <<'PY'
import datetime as dt
import hashlib
import json
import pathlib
import sys

bundle_dir = pathlib.Path(sys.argv[1])
stamp = sys.argv[2]

def classify(name: str) -> str:
    if name.startswith("doctor-report"):
        return "doctor"
    if name == "proof-sop-checklist.md":
        return "proof_sop_checklist"
    if name.endswith(".json") and "proof" in name:
        return "proof_json"
    if name == "preflight-last.log":
        return "preflight_log"
    if name == "deploy-v01-eth.json":
        return "deploy_artifact"
    if name == "v01-console-config.json":
        return "frontend_config"
    return "other"

files = []
for path in sorted(bundle_dir.rglob("*")):
    if not path.is_file():
        continue
    content = path.read_bytes()
    files.append(
        {
            "path": str(path.relative_to(bundle_dir)),
            "kind": classify(path.name),
            "sizeBytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    )

index = {
    "indexVersion": "proof-index-v1",
    "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "bundleStamp": stamp,
    "fileCount": len(files),
    "files": files,
}

canonical = json.dumps(index, sort_keys=True, separators=(",", ":")).encode("utf-8")
index["manifestDigest"] = hashlib.sha256(canonical).hexdigest()
(bundle_dir / "proof-index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
print(index["manifestDigest"])
PY
)"

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
echo "proof-index manifest digest (sha256): ${MANIFEST_DIGEST}"
echo "Share this zip file with maintainers for faster troubleshooting."
