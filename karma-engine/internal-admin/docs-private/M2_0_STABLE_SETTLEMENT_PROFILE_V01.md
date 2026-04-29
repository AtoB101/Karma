# M2.0 Stable Settlement Profile v0.1

This profile introduces a first on-chain settlement safety baseline for stablecoin-oriented flows.

## Goals

- constrain bill creation to explicitly allowed tokens when enforcement is enabled
- prevent dust-level bill creation via minimum bill amount
- keep rollout controlled with owner-managed toggles
- expose profile state directly in frontend health checks and evidence exports

## Contract controls

Implemented in `NonCustodialAgentPayment`:

- `setStableTokenEnforcement(bool enabled)`
  - when enabled, `createBill` requires token allowlist approval
- `setStableTokenAllowed(address token, bool allowed)`
  - owner-managed stable token allowlist flag
- `setMinSettlementAmount(uint256 amount)`
  - global minimum principal amount for `createBill`

Views:

- `stableTokenEnforcementEnabled()`
- `isStableTokenAllowed(address token)`
- `minSettlementAmount()`

Events:

- `StableTokenEnforcementUpdated(bool enabled)`
- `StableTokenAllowedUpdated(address indexed token, bool allowed)`
- `MinSettlementAmountUpdated(uint256 amount)`

## Enforcement points

### `createBill(...)`

Now checks:

1. `amount >= minSettlementAmount`
2. if `stableTokenEnforcementEnabled == true`, then `isStableTokenAllowed(token) == true`

## Frontend operations panel (M2.0)

In `examples/v01-metamask-settlement.html`, stable profile controls are available in:

- **Stable settlement profile (M2.0)** section
- Inputs:
  - `stableEnforcementEnabled`
  - `stableMinAmount`
  - `stableTokenRule`
  - `stableTokenAllowed`
- Actions:
  - `Apply stable profile` (updates enforcement + min amount)
  - `Set stable token rule` (updates token allowlist)
  - `Refresh stable profile` (reads current on-chain state)

Health check (`Run Health Check`) also reads stable profile and emits `stable_settlement` diagnostics.

## Evidence integration (M2.1)

Exported diagnosis JSON now carries stable profile context in three places:

- `authSnapshot.stableSettlementSnapshot`
- `requestSnapshot.stableSettlementDecision`
- `riskSnapshot.stableSettlement`

## Evidence integration (M2.3 extension)

Stable profile change history now includes richer operation metadata under:

- `authSnapshot.stableConfigHistory[]`

Each history item includes:

- `version` (monotonic local version counter in UI session)
- `action` (for example: `apply_profile`, `set_token_rule`)
- `reason` (operator-supplied change reason)
- `operator` (operator label, for example `alice@ops`)
- `tokenAddress`
- `tokenAllowed`
- `enforcementEnabled`
- `minSettlementAmount`
- `txHashes` (transaction hash references per change operation)

This allows audit/support to answer:

- Was stable enforcement enabled at operation time?
- Was the active token allowlisted?
- Was the configured amount above minimum threshold?
- Did stable settlement constraints contribute to readiness outcome?

## Evidence integration (M2.4 hash-chain extension)

To strengthen tamper-evidence for local operation history, each stable config history item now
includes chained digests:

- `prevHash` (hash pointer to previous history record in this session; `null` on first record)
- `currentHash` (hash of canonicalized record content including `prevHash`)

Hashing rules in current frontend implementation:

- algorithm: `keccak256`
- input encoding: UTF-8 bytes of canonical JSON payload
- canonical payload keys:
  - `version`
  - `traceId`
  - `timestamp`
  - `action`
  - `reason`
  - `operator`
  - `tokenAddress`
  - `tokenAllowed`
  - `enforcementEnabled`
  - `minSettlementAmount`
  - `txHashes`
  - `prevHash`

This enables quick integrity checks across exported history items by recomputing hashes in order.

## Evidence integration (M2.5 verification extension)

Frontend now supports one-click integrity verification from the export panel:

- UI action: `Verify stable hash chain`
- implementation: recompute `currentHash` over each history record and validate `prevHash` linkage

Exported fields now include verification results:

- `riskSnapshot.stableHistoryIntegrity` (`pass | fail`)
- `riskSnapshot.stableHistoryBreakIndex` (first broken index or `null`)
- `riskSnapshot.stableHistoryCheckedCount` (number of checked records)
- `riskSnapshot.stableHistoryVerification` (full verifier output object)

## Evidence integration (M2.6 offline file verification extension)

Frontend now supports offline verification against an exported diagnosis JSON file,
without on-chain RPC access:

- UI action: `Verify from JSON file`
- input source: local file picker (`.json`) from operator machine
- verification target: `authSnapshot.stableConfigHistory[]` inside imported JSON
- verification method: same canonical hash-chain verifier used for live in-memory history

Result behavior:

- writes `stable_chain` diagnostic (low on pass, high on fail)
- writes output step `stable_chain_verification_file`
- includes file metadata and verification summary:
  - `filename`
  - `recordCount`
  - `ok`
  - `breakIndex`
  - `checkedCount`
  - `reason` (when failed)

## Evidence integration (M2.7 proof-export extension)

To support compliance/audit handoff, frontend can now export a compact proof JSON
from the latest offline verification result:

- UI action: `Export stable proof`
- precondition: at least one successful/failed `Verify from JSON file` run in current session

Proof JSON includes:

- `proofType` (`stable_chain_verification_proof_v1`)
- `generatedAt`
- `app`
- `sourceFile`
- `verification`:
  - `ok`
  - `checkedCount`
  - `breakIndex`
  - `reason`
  - `expectedHash`
  - `actualHash`
- `summary`:
  - `stableConfigVersion`
  - `stableConfigChainHead`
  - `stableHistoryIntegrity`

## Evidence integration (M2.8 proof-signature extension)

To make the proof artifact independently attestable, frontend now supports wallet signing
of proof digest (EIP-191 style personal message via `signMessage`):

- UI action: `Sign stable proof`
- precondition:
  - wallet connected
  - at least one imported JSON verification result in current session

Signature flow:

1. Build canonical proof object from latest imported verification context.
2. Hash canonical proof JSON with `keccak256(utf8Bytes(json))` as `proofDigest`.
3. Ask wallet to sign `proofDigest` string via `signMessage`.
4. Persist signature block into proof:
   - `signature.digest`
   - `signature.wallet`
   - `signature.scheme` (`eip191_personal_sign`)
   - `signature.signedAt`
   - `signature.value` (hex signature)

Export behavior:

- `Export stable proof` now includes `signature` when present.
- diagnosis export snapshots latest proof with signature in:
  - `riskSnapshot.importedStableProofReport`

## Evidence integration (M2.9 proof-signature verify extension)

Frontend now supports offline verification of a signed proof JSON:

- UI action: `Verify proof signature`
- input source: local signed proof JSON file (`.json`)
- verification checks:
  1. rebuild canonical proof signing payload and recompute `digest`
  2. recover signer from `message + signature`
  3. compare recovered signer with declared signer in proof
  4. compare recomputed digest with declared digest in proof

Result behavior:

- writes diagnostic kind `stable_chain_proof` (low on pass, high on fail)
- writes output step `stable_proof_signature_verified`
- stores latest verify result into:
  - `riskSnapshot.importedStableProofSignatureVerification`

## Suggested rollout

1. Deploy with enforcement disabled (default) and set desired `minSettlementAmount`.
2. Populate token allowlist for target stablecoins.
3. Enable `stableTokenEnforcementEnabled`.
4. Use frontend refresh + health check to verify profile status.
5. Validate evidence export includes stable settlement fields.

## M3.9 batch patrol policy extension

Batch verifier now supports stronger patrol admission controls for scheduled jobs:

- `--min-total <n>`: require at least `n` matched bundles after glob/time filtering.
- `--require-recent-pass <hours>`: require at least one passing bundle whose timestamp
  is within the last `<hours>` from current UTC time.

These controls are implemented in:

- `scripts/verify-proof-index-batch.sh`

And reflected in JSON summary fields:

- `minTotal`
- `requireRecentPassHours`
- `recentPassThreshold`
- `policy.minTotalViolated`
- `policy.recentPassViolated`
- `ok`

## Validation commands (operator quick checks)

Local tests:

```bash
forge test --match-path "contracts/test/NonCustodialAgentPayment.t.sol" -vv
```

Frontend:

```bash
python3 -m http.server 8790
```

Open:

```text
http://127.0.0.1:8790/examples/v01-metamask-settlement.html
```

Manual verification checklist:

1. Connect wallet.
2. Apply stable profile with enforcement off and min amount set.
3. Set stable token rule for target token.
4. Enable enforcement and refresh stable profile.
5. Run health check and confirm `stable_settlement` diagnostics appear.
6. Export JSON and verify stable fields exist in `authSnapshot`, `requestSnapshot`, and `riskSnapshot`.

## Known limitations in M2.0

- token-level rules are global (owner-managed), not per-buyer profile yet
- no decimal-aware floor normalization yet (raw base units only)
- no multi-chain token profile registry yet
