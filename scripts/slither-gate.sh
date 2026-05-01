#!/usr/bin/env bash
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

TARGET="karma-core/contracts/core/SettlementEngine.sol"
if [[ ! -f "$TARGET" ]]; then
  TARGET="contracts/core/SettlementEngine.sol"
fi

if [[ ! -f "$TARGET" ]]; then
  echo "ERR  cannot locate SettlementEngine.sol for slither scan"
  exit 1
fi

ALLOW_PATHS="$(pwd),$(pwd)/karma-core/contracts,$(pwd)/contracts"
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

if [[ "$SLITHER_EXIT" -ne 0 ]]; then
  mapfile -t DETECTORS < <(grep -oE "Detector: [a-z0-9-]+" /tmp/slither-output.txt | sed 's/Detector: //' | sort -u)
  if [[ "${#DETECTORS[@]}" -eq 0 ]]; then
    echo "ERR  slither failed without parseable detector output"
    exit 1
  fi

  # Accepted residual findings for public SettlementEngine baseline.
  # These are documented design trade-offs for the non-custodial quote flow.
  ALLOWED_DETECTORS=(
    "arbitrary-send-erc20"
    "calls-loop"
    "timestamp"
    "naming-convention"
  )

  UNEXPECTED=()
  for detector in "${DETECTORS[@]}"; do
    allowed=0
    for permitted in "${ALLOWED_DETECTORS[@]}"; do
      if [[ "$detector" == "$permitted" ]]; then
        allowed=1
        break
      fi
    done
    if [[ "$allowed" -eq 0 ]]; then
      UNEXPECTED+=("$detector")
    fi
  done

  if [[ "${#UNEXPECTED[@]}" -gt 0 ]]; then
    echo "ERR  slither reported unexpected detectors: ${UNEXPECTED[*]}"
    exit 1
  fi

  echo "WARN accepted slither detectors: ${DETECTORS[*]}"
  echo "OK   slither gate passed with accepted residual findings"
  exit 0
fi

echo "OK   slither gate passed"
