# Security Acceptance Notes

This document records currently accepted static-analysis findings for the
public protocol baseline.

## Accepted Findings (Current)

### 1) `arbitrary-send-erc20` in `SettlementEngine._submitSettlement`
- Context: Slither flags `transferFrom(quote.payer, quote.payee, quote.amount)`.
- Rationale: `quote.payer`, `quote.payee`, and `quote.amount` are covered by
  signed EIP-712 quote data and nonce replay protection.
- Additional controls:
  - signature verification with strict digest
  - nonce uniqueness (`usedQuoteIds`)
  - deadline enforcement
  - token allowlist checks

### 2) `calls-loop` in `SettlementEngine.settleBatch`
- Context: `settleBatch` iterates through quotes and performs ERC20 transfers.
- Rationale: batch settlement is an intentional capability.
- Additional controls:
  - explicit max batch size bound
  - non-reentrant settlement path
  - failure reverts preserve accounting consistency

### 3) `timestamp` comparisons
- Context: deadline checks compare against `block.timestamp`.
- Rationale: deadline semantics require timestamp ordering.
- Additional controls:
  - deadlines are short-lived quote constraints
  - validator skew impact is bounded to normal timestamp tolerance

### 4) `naming-convention` (`DOMAIN_SEPARATOR`)
- Context: style-only warning from static analysis.
- Rationale: no security impact.

## Policy

- Findings above are accepted for current public baseline and tracked for future
  hardening.
- Any new high/critical findings must fail CI and block merge.
