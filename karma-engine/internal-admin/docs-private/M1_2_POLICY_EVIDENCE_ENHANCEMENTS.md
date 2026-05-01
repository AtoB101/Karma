## M1.2 Enhancements: Policy Readability + Evidence Decisions

This note documents the M1.2 scope:

1. Improve policy error readability in UI logs/output.
2. Extend evidence exports with policy decision context.

### 1) Readable policy error mapping

The frontend runtime classifier now maps policy-related contract errors to explicit, actionable kinds:

- `policy_per_tx_exceeded`
- `policy_daily_exceeded`
- `policy_payee_blocked`
- `policy_token_blocked`
- `policy_rate_limit_exceeded`
- `policy_not_configured`
- `policy_expired`
- `policy_scope_blocked`
- `policy_blocked`

This ensures operators can quickly understand why an action was rejected without manually decoding revert strings.

### 2) Evidence export policy context

Diagnosis JSON now includes:

- `authSnapshot.policySnapshot`
  - current policy settings (enabled, limits, window, allowlist toggles)
  - current usage counters
  - optional checks against current payee/token fields
- `executionSnapshot.policyDecision`
  - latest policy-related diagnostic entry (title/detail/timestamp)
  - fallback note when no policy decision has been recorded yet

This allows support/audit teams to answer:

- What policy was active at execution time?
- Was an action allowed or blocked by policy?
- What was the exact policy reason?
