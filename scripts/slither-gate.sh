#!/usr/bin/env bash
# Slither gate for the active bilateral settlement contract (KarmaBilateral).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

FORMAT="text"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --format)
      FORMAT="${2:-text}"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

if ! command -v slither >/dev/null 2>&1; then
  echo "ERR  slither is not installed"
  exit 1
fi

TARGET="karma-core/contracts/core/KarmaBilateral.sol"
if [[ ! -f "$TARGET" ]]; then
  echo "ERR  cannot locate KarmaBilateral.sol for slither scan"
  exit 1
fi

ALLOW_PATHS="$(pwd),$(pwd)/karma-core/contracts"
echo "Running slither on: $TARGET"
set +e
slither "$TARGET" --solc-args "--allow-paths $ALLOW_PATHS" --exclude-dependencies > /tmp/slither-output.txt 2>&1
SLITHER_EXIT=$?
set -e

if [[ "$FORMAT" == "text" ]]; then
  cat /tmp/slither-output.txt
fi

if grep -q "No contract was analyzed" /tmp/slither-output.txt; then
  echo "ERR  slither analyzed zero contracts"
  exit 1
fi

# Fail only on high-confidence critical detectors; informational findings are accepted.
CRITICAL_DETECTORS=(
  "reentrancy-eth"
  "reentrancy-no-eth"
  "suicidal"
  "controlled-delegatecall"
  "arbitrary-send-eth"
)

if [[ "$SLITHER_EXIT" -ne 0 ]]; then
  mapfile -t DETECTORS < <(grep -oE "Detector: [a-z0-9-]+" /tmp/slither-output.txt | sed 's/Detector: //' | sort -u)
  if [[ "${#DETECTORS[@]}" -eq 0 ]]; then
    echo "ERR  slither failed without parseable detector output"
    exit 1
  fi

  CRITICAL_HIT=()
  for detector in "${DETECTORS[@]}"; do
    for critical in "${CRITICAL_DETECTORS[@]}"; do
      if [[ "$detector" == "$critical" ]]; then
        CRITICAL_HIT+=("$detector")
      fi
    done
  done

  if [[ "${#CRITICAL_HIT[@]}" -gt 0 ]]; then
    echo "ERR  slither reported critical detectors: ${CRITICAL_HIT[*]}"
    exit 1
  fi

  echo "WARN accepted non-critical slither detectors: ${DETECTORS[*]}"
  echo "OK   slither gate passed with accepted residual findings"
  exit 0
fi

echo "OK   slither gate passed"
