# Proof Verification SOP (Stable Settlement Evidence)

This SOP defines a practical, repeatable workflow for generating, signing, and verifying
stable-settlement proof artifacts in the TrustChain console.

Scope:
- frontend file: `examples/v01-metamask-settlement.html`
- evidence fields under exported diagnosis JSON `riskSnapshot.*`
- proof artifact exported as `trustchain-stable-proof-*.json`

## 1) Roles and responsibilities

- Operator
  - runs console actions and exports JSON artifacts
  - signs proof when needed
- Reviewer / Auditor
  - verifies stable hash-chain integrity from imported diagnosis JSON
  - verifies proof signature from imported proof JSON
  - records pass/fail decision

## 2) Preconditions

1. Frontend console is running:
   - `http://127.0.0.1:8790/examples/v01-metamask-settlement.html`
2. Browser wallet extension is available (for signing step).
3. You have at least one exported diagnosis JSON file from TrustChain console.

## 3) End-to-end workflow

### Step A — Verify stable chain from diagnosis JSON (offline)

1. Click `Verify from JSON file`.
2. Select a previously exported diagnosis JSON file.
3. Confirm output step is `stable_chain_verification_file`.
4. Confirm diagnostics include a `stable_chain` entry.

Expected key result fields:
- `ok`
- `checkedCount`
- `breakIndex`
- `reason` (present when failed)

### Step B — Export stable proof artifact

1. Click `Export stable proof`.
2. Downloaded file name format:
   - `trustchain-stable-proof-<timestamp>.json`
3. Confirm output step is `stable_proof_exported`.

Expected proof core fields:
- `proofType`
- `proofVersion`
- `source`
- `verification`
- `chain`

### Step C — Sign stable proof digest (optional but recommended)

1. Connect wallet if not connected.
2. Click `Sign stable proof`.
3. Approve wallet signature request.
4. Confirm output step is `stable_proof_signed`.

Expected proof attestation fields:
- `attestation.standard` (`eip191_signMessage`)
- `attestation.signer`
- `attestation.digest`
- `attestation.message`
- `attestation.signature`
- `attestation.signedAt`

### Step D — Verify proof signature from proof JSON (offline)

1. Click `Verify proof signature`.
2. Select a proof JSON file (exported in Step B, optionally signed in Step C).
3. Confirm output step is `stable_proof_signature_verified`.
4. Confirm diagnostics include kind `stable_chain_proof`.

Expected verification fields:
- `ok`
- `digestMatches`
- `signerMatches`
- `declaredSigner`
- `recoveredSigner`
- `digest`
- `recomputedDigest`

Pass condition:
- `ok == true`

## 4) Evidence fields to archive

When exporting diagnosis JSON, archive these fields from `riskSnapshot`:

- `stableHistoryIntegrity`
- `stableHistoryBreakIndex`
- `stableHistoryCheckedCount`
- `stableHistoryVerification`
- `importedStableHistoryVerification`
- `importedStableProofReport`
- `importedStableProofSignatureVerification`

## 5) Failure handling guide

### A) Hash-chain verification failed

Symptoms:
- `stableHistoryIntegrity = fail`
- `stableHistoryBreakIndex` not null

Actions:
1. Re-run `Verify from JSON file` on the original artifact.
2. Check if JSON was modified in transit.
3. Export a fresh diagnosis JSON from source environment and compare.

### B) Proof signature verification failed

Symptoms:
- `digestMatches = false` or `signerMatches = false`

Actions:
1. Ensure proof JSON corresponds to the exact file that was signed.
2. Confirm no post-sign edits were made to proof core fields.
3. Re-sign using `Sign stable proof` and verify again.

## 6) Minimum acceptance checklist

- [ ] Offline chain verification executed (`stable_chain_verification_file`)
- [ ] Proof JSON exported (`stable_proof_exported`)
- [ ] Proof signature generated (`stable_proof_signed`) if signature is required
- [ ] Offline signature verification executed (`stable_proof_signature_verified`)
- [ ] Archived diagnosis JSON contains all required `riskSnapshot` verification fields

## 7) SOP execution record template (M3.1)

You can generate a timestamped checklist artifact for team handoff:

```bash
./scripts/proof-sop-checklist.sh
```

Optional metadata:

```bash
./scripts/proof-sop-checklist.sh \
  --operator "alice@ops" \
  --reviewer "bob@audit" \
  --ticket "INC-2026-0428-01"
```

Output:
- `results/proof-sop-checklist-<timestamp>.md`
- `results/proof-sop-checklist-latest.md` (latest copy for quick access)

This file is intended for process traceability and audit archive, and can be attached
to incident/postmortem tickets together with diagnosis/proof JSON artifacts.

## 8) Support bundle integration (M3.2)

`make support-bundle` now auto-generates and includes the SOP checklist template.

In bundled zip you should see:
- `proof-sop-checklist-latest.md`

Optional metadata passthrough:

```bash
./scripts/support-bundle.sh \
  --operator "alice@ops" \
  --reviewer "bob@audit" \
  --ticket "INC-2026-0428-01"
```

