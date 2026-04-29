# TrustChain Evidence Schema v0.1 (Frozen for M1)

This document defines the **field contract** for exported diagnosis JSON in M1.
The goal is to keep support/audit parsers stable while M2 adds new fields.

## Schema freeze policy (M1, compatibility updated in M4.0)

- `schemaVersion = "evidence-v1"` is the canonical schema marker.
- `evidenceVersion = "evidence-v1"` is preserved as a compatibility alias.
- Existing field names below are frozen for M1 and must not be renamed.
- New optional fields may be appended in M2+, but existing fields must remain backward compatible.
- `reportVersion` is legacy and transitional (`"1.1"` in current exporter); consumers should key on `schemaVersion` first.

## Top-level fields

- `reportVersion` (legacy compatibility)
- `schemaVersion` (canonical schema marker)
- `evidenceVersion` (compatibility alias)
- `traceId`
- `app`
- `exportedAt`
- `userAgent`
- `pageUrl`
- `network`
- `walletAddress`
- `kpis`
- `autoMonitor`
- `authSnapshot`
- `requestSnapshot`
- `executionSnapshot`
- `riskSnapshot`

## authSnapshot

- `walletAddress`
- `signaturePresent`
- `quotePresent`
- `stableSettlementSnapshot` (string snapshot shown in UI; optional in M1, expected in M2.1+)
- `stableConfigVersion` (current local stable config history version counter; expected in M2.3+)
- `latestStableChangeReason` (latest stable config change reason; nullable, expected in M2.3+)
- `latestStableOperator` (latest stable config operator label; nullable, expected in M2.3+)
- `stableConfigHistory[]` (stable settlement config change log; expected in M2.2+)
  - `version` (monotonic integer, starts from 1 in current session)
  - `prevHash` (hash pointer to previous history item hash; genesis uses `0x0`)
  - `currentHash` (hash of canonicalized current history item)
  - `traceId`
  - `timestamp`
  - `action` (`apply_profile | set_token_rule`)
  - `reason` (operator-provided reason text; expected in M2.3+)
  - `operator` (operator label; expected in M2.3+)
  - `tokenAddress` (nullable)
  - `tokenAllowed` (nullable boolean)
  - `enforcementEnabled` (optional boolean)
  - `minSettlementAmount` (optional string)
  - `txHashes` (object with tx hash fields present for the performed action)

## requestSnapshot

- `form`:
  - `engineAddress`
  - `nonCustodialAddress`
  - `tokenAddress`
  - `payeeAddress`
  - `amount`
  - `scopeText`
  - `proofHashText`
  - `ttlSeconds`
- `logFilters`:
  - `kind`
  - `severity`
- `policySnapshot` (string snapshot shown in UI)
- `policyDecision`:
  - `result` (`allowed | blocked | unknown`)
  - `reasonKind`
  - `reasonTitle`
  - `detail`
  - `decidedAt`
- `stableSettlementSnapshot` (string snapshot shown in UI)
- `stableSettlementDecision`:
  - `result` (`allowed | blocked | unknown`)
  - `reasonKind`
  - `reasonTitle`
  - `detail`
  - `decidedAt`

## executionSnapshot

- `diagnostics[]`:
  - `id`
  - `traceId`
  - `timestamp`
  - `kind`
  - `severity`
  - `title`
  - `detail`
  - `payload`
- `transactionHistory[]`:
  - `traceId`
  - `timestamp`
  - `status`
  - `txHash`
  - `blockNumber`
  - `amount`
- `lastQuote`:
  - `quoteId`
  - `payer`
  - `payee`
  - `token`
  - `amount`
  - `nonce`
  - `deadline`
  - `scopeHash`

## riskSnapshot

- `summary.totalDiagnostics`
- `summary.high`
- `summary.medium`
- `summary.low`
- `latestHighRiskTitle`
- `latestStableRiskTitle`
- `stableConfigChanges` (count of stable config changes captured in current evidence)
- `latestStableConfigVersion` (latest stable config history version; nullable)
- `stableConfigChainHead` (latest stable history `currentHash`; nullable)
- `stableHistoryIntegrity` (`pass | fail`; result of hash-chain verification)
- `stableHistoryBreakIndex` (nullable integer; first failing index when integrity is `fail`)
- `stableHistoryCheckedCount` (integer; number of records checked)
- `stableHistoryVerification` (object with detailed verification output)
- `importedStableHistoryVerification` (object; last offline verification result for imported diagnosis JSON; nullable)
  - `source` (`imported_json`)
  - `fileName`
  - `ok`
  - `checkedCount`
  - `breakIndex`
  - `reason` (nullable)
  - `expectedHash` (nullable)
  - `actualHash` (nullable)
- `importedStableProofReport` (object; exportable lightweight proof snapshot for legal/audit handoff; nullable)
  - `proofVersion` (currently `stable-proof-v1`)
  - `generatedAt` (ISO timestamp)
  - `source` (`imported_json`)
  - `fileName`
  - `recordCount`
  - `chainHead` (latest `currentHash` in imported history, nullable)
  - `integrity` (`pass | fail`)
  - `breakIndex` (nullable)
  - `checkedCount`
  - `reason` (nullable)
  - `expectedHash` (nullable)
  - `actualHash` (nullable)
  - `signature` (nullable object; present when user signs proof digest in M2.8+)
    - `scheme` (`eip191_signMessage`)
    - `signer` (wallet address)
    - `signedAt` (ISO timestamp)
    - `digest` (`keccak256` of canonical proof summary payload)
    - `message` (human-readable signable string including digest)
    - `signature` (hex string)
- `importedStableProofSignatureVerification` (object; result of local signature verification for imported proof JSON; nullable)
  - `source` (`proof_json`)
  - `fileName`
  - `ok` (boolean)
  - `digestMatches` (boolean)
  - `signerMatches` (boolean)
  - `declaredSigner` (proof-declared signer)
  - `recoveredSigner` (locally recovered signer from signature)
  - `digest` (declared digest in proof)
  - `recomputedDigest` (local recomputed digest)
  - `signature` (hex signature value used for recovery)
- `stableSettlement`:
  - `enforcementEnabled` (nullable boolean)
  - `minSettlementAmount` (nullable string)
  - `tokenRuleResult` (nullable boolean)
  - `latestStableDecision` (`allowed | blocked | unknown`)
