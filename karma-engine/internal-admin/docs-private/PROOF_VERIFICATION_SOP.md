# Proof Verification SOP (Stable Settlement Evidence)

This SOP defines a practical, repeatable workflow for generating, signing, and verifying
stable-settlement proof artifacts in the Karma console.

Scope:
- frontend file: `examples/v01-metamask-settlement.html`
- evidence fields under exported diagnosis JSON `riskSnapshot.*`
- proof artifact exported as `karma-stable-proof-*.json`

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
3. You have at least one exported diagnosis JSON file from Karma console.

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
   - `karma-stable-proof-<timestamp>.json`
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

`make support-bundle` now auto-generates and includes the SOP checklist template,
and writes a bundle manifest with sha256 fingerprints.

In bundled zip you should see:
- `proof-sop-checklist.md`
- `proof-index.json`

Optional metadata passthrough:

```bash
./scripts/support-bundle.sh \
  --operator "alice@ops" \
  --reviewer "bob@audit" \
  --ticket "INC-2026-0428-01"
```

`proof-index.json` contains:
- bundle metadata (`generatedAt`, `bundleStamp`, `fileCount`)
- integrity marker:
  - `manifestDigest` (sha256 over canonical index content excluding `manifestDigest`)
- per-artifact entries:
  - `path`
  - `sizeBytes`
  - `sha256`

You can verify this digest locally:

```bash
./scripts/verify-proof-index.sh --path "results/support-bundle-<timestamp>.zip"
```

Batch verification across a directory:

```bash
./scripts/verify-proof-index-batch.sh --dir results --format json --output results/proof-index-batch-report.json
```

Optional policy controls for CI/ops:

```bash
./scripts/verify-proof-index-batch.sh \
  --dir results \
  --since 20260428T120000Z \
  --until 20260428T130000Z \
  --strict
```

- `--strict`: fail if no bundle matched selection.
- `--max-fail N`: fail when verified failures exceed `N`.
- `--since/--until`: filter bundles by timestamp in filename (`support-bundle-YYYYmmddTHHMMSSZ.zip`), supports compact and ISO8601 input.
- `--min-total N`: fail when matched sample size is less than `N`.
- `--require-recent-pass H`: fail when latest passing bundle is older than `H` hours (UTC).
- CI gate wrapper:
  - `./scripts/ci-proof-gates.sh` runs:
    1) evidence schema validation on `docs/samples/karma-evidence-sample-v1.json`
    2) batch proof-index verification with strict policy profile (`--strict --max-fail 0 --min-total 1 --require-recent-pass 24`)
- patrol profile wrapper (M4.2):
  - `./scripts/proof-patrol.sh --profile <strict|balanced|lenient>`
  - outputs:
    - batch summary JSON (`results/proof-patrol-batch-latest.json`)
    - alert JSON (`results/proof-patrol-alert-latest.json`)
  - alert JSON fields include:
    - `status` (`pass|fail`)
    - `severity` (`info|warning|critical`)
    - `policy`
    - `reasonSummary`
    - `nextActions`
- batch summary fields:
  - `reasonSummary`: fail reasons grouped by count
  - `latestPassAt`: latest bundle stamp among pass rows (if present)
  - `policy`: policy violation booleans (`strictNoMatchViolated`, `maxFailViolated`, `minTotalViolated`, `recentPassViolated`)
  - `ok`: final gate decision for CI/ops

Expected terminal result:
- `PASS` when digest matches canonical recomputation
- `FAIL` with mismatch reason/details otherwise

