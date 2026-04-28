#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${ROOT_DIR}/results"
OUT_PATH=""
OPERATOR="${OPERATOR:-unknown-operator}"
REVIEWER="${REVIEWER:-unknown-reviewer}"
TICKET="${TICKET:-N/A}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/proof-sop-checklist.sh [--output <path>] [--operator <name>] [--reviewer <name>] [--ticket <id>]

Description:
  Generates a SOP execution checklist template for proof verification runs.
  The generated markdown can be attached to audit/compliance records.

Options:
  --output <path>     Output markdown path (default: results/proof-sop-checklist-<timestamp>.md)
  --operator <name>   Operator name/label (default: unknown-operator)
  --reviewer <name>   Reviewer/Auditor name/label (default: unknown-reviewer)
  --ticket <id>       Internal ticket/case ID (default: N/A)
  -h, --help          Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      [[ $# -lt 2 ]] && { echo "Error: --output requires a value"; exit 1; }
      OUT_PATH="$2"
      shift 2
      ;;
    --operator)
      [[ $# -lt 2 ]] && { echo "Error: --operator requires a value"; exit 1; }
      OPERATOR="$2"
      shift 2
      ;;
    --reviewer)
      [[ $# -lt 2 ]] && { echo "Error: --reviewer requires a value"; exit 1; }
      REVIEWER="$2"
      shift 2
      ;;
    --ticket)
      [[ $# -lt 2 ]] && { echo "Error: --ticket requires a value"; exit 1; }
      TICKET="$2"
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
  OUT_PATH="${RESULTS_DIR}/proof-sop-checklist-${STAMP}.md"
fi
mkdir -p "$(dirname "$OUT_PATH")"

cat >"$OUT_PATH" <<EOF
# Proof Verification SOP Execution Record

- Generated at (UTC): ${STAMP}
- Repository: $(basename "$ROOT_DIR")
- SOP doc: docs/PROOF_VERIFICATION_SOP.md

## Context

- Ticket/Case: ${TICKET}
- Operator: ${OPERATOR}
- Reviewer/Auditor: ${REVIEWER}
- Environment (dev/staging/prod): ____________________
- Console URL used: http://127.0.0.1:8790/examples/v01-metamask-settlement.html

## Input Artifacts

- Diagnosis JSON file: ____________________
- Proof JSON file (if produced): ____________________
- Wallet used for signing (if applicable): ____________________

## SOP Step Log

### A) Verify from JSON file
- [ ] Executed
- Output step: ____________________ (expect: stable_chain_verification_file)
- Result ok: ____________________
- checkedCount: ____________________
- breakIndex: ____________________
- reason (if failed): ____________________

### B) Export stable proof
- [ ] Executed
- Output step: ____________________ (expect: stable_proof_exported)
- Exported proof file: ____________________
- proofVersion: ____________________
- chain.headHash: ____________________

### C) Sign stable proof (optional)
- [ ] Executed (if required)
- Output step: ____________________ (expect: stable_proof_signed)
- attestation.standard: ____________________ (expect: eip191_signMessage)
- attestation.signer: ____________________
- attestation.digest: ____________________
- attestation.signedAt: ____________________

### D) Verify proof signature from proof JSON
- [ ] Executed
- Output step: ____________________ (expect: stable_proof_signature_verified)
- Result ok: ____________________
- digestMatches: ____________________
- signerMatches: ____________________
- declaredSigner: ____________________
- recoveredSigner: ____________________

## Evidence Snapshot Checklist (riskSnapshot)

- [ ] stableHistoryIntegrity
- [ ] stableHistoryBreakIndex
- [ ] stableHistoryCheckedCount
- [ ] stableHistoryVerification
- [ ] importedStableHistoryVerification
- [ ] importedStableProofReport
- [ ] importedStableProofSignatureVerification

## Final Decision

- Decision: [ ] PASS   [ ] FAIL
- Reviewer notes:

____________________________________________________________
____________________________________________________________
____________________________________________________________

## Sign-off

- Operator sign-off: ____________________  Date: ____________________
- Reviewer sign-off: ____________________  Date: ____________________
EOF

echo "Proof SOP checklist generated: ${OUT_PATH}"
echo "Fill this markdown and archive with proof artifacts."
