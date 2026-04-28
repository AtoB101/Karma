# TrustChain Evidence Schema v0.1

This schema standardizes exported diagnosis JSON for audit, support, and policy analysis.

## Top-level fields

- `evidenceVersion`: schema version string (e.g. `1.0`)
- `app`: application name
- `traceId`: unique per-export trace id
- `exportedAt`: ISO timestamp
- `userAgent`: browser agent string
- `pageUrl`: current page URL
- `network`: chain metadata (`chainId`, `name`) or error info
- `walletAddress`: full wallet address if connected

## Authorization snapshot

`authorizationSnapshot` summarizes what authorization context existed at export time.

- `walletConnected`: boolean
- `signaturePresent`: boolean
- `scopeText`: current scope input
- `proofHashText`: current proof hash input
- `deadlineTtlSeconds`: current TTL input
- `lastQuoteSummary`:
  - `quoteId`
  - `payer`
  - `payee`
  - `token`
  - `amount`
  - `nonce`
  - `deadline`
  - `scopeHash`

## Request snapshot

`requestSnapshot` captures current operator inputs.

- `engineAddress`
- `nonCustodialAddress`
- `tokenAddress`
- `payeeAddress`
- `amount`
- `scopeText`
- `proofHashText`
- `ttlSeconds`

## Execution snapshot

`executionSnapshot` captures runtime health and state context.

- `autoMonitor`: `{ active, pollSeconds }`
- `logFilters`: `{ kind, severity }`
- `kpis`:
  - `wallet`
  - `engine`
  - `tokenAllowlist`
  - `settlementReadiness`
  - `nonCustodialLocked`
  - `nonCustodialActive`
  - `nonCustodialReserved`
  - `nonCustodialInvariant`

## Risk snapshot

`riskSnapshot` contains the latest high/medium/low diagnostics for risk review.

- `totalDiagnostics`
- `bySeverity`: counts per severity
- `latestHigh`: latest high-severity entry or `null`
- `latestMedium`: latest medium-severity entry or `null`
- `latestLow`: latest low-severity entry or `null`

## Diagnostics and tx history

- `diagnostics`: array of diagnostic entries
  - `id`, `timestamp`, `kind`, `severity`, `title`, `detail`, `payload`
- `transactionHistory`: array of tx status entries from UI

## Compatibility note

Legacy exports used `reportVersion`; new exports use `evidenceVersion`.
For backward compatibility, exporters may include both during transition.
