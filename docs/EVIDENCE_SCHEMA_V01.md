# TrustChain Evidence Schema v0.1 (Frozen for M1)

This document defines the **field contract** for exported diagnosis JSON in M1.
The goal is to keep support/audit parsers stable while M2 adds new fields.

## Schema freeze policy (M1)

- `evidenceVersion = "evidence-v1"` is the canonical schema marker.
- Existing field names below are frozen for M1 and must not be renamed.
- New optional fields may be appended in M2+, but existing fields must remain backward compatible.
- `reportVersion` is legacy and transitional (`"1.1"` in current exporter); consumers should key on `evidenceVersion`.

## Top-level fields

- `reportVersion` (legacy compatibility)
- `evidenceVersion` (canonical schema marker)
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
