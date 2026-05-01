# Policy Engine v0.1 (M1/M1.1)

This document defines the first production policy controls for `NonCustodialAgentPayment`.

## Goals

- enforce spend controls before bill creation
- enforce owner-level authorization for batch close/settle operations
- expose policy/usage state for operator dashboards

## On-chain policy model

`INonCustodialAgentPayment.Policy`:

- `perTxLimit`: max principal per bill creation
- `dailyLimit`: max principal sum per 24h bucket
- `maxTxPerWindow`: max bill-create count per window
- `windowSeconds`: rate-limit window size
- `enabled`: toggle checks on/off
- `hasPayeeRules`: whether payee allowlist is active
- `hasTokenRules`: whether token allowlist is active

`INonCustodialAgentPayment.PolicyUsage`:

- `dayStart`: current day bucket start timestamp
- `spentToday`: cumulative principal in day bucket
- `windowStart`: current window bucket start timestamp
- `txCountInWindow`: create-bill count in current window

## Enforcement points

### 1) Bill creation

`createBill(...)` enforces:

- policy enabled check
- policy expiry check
- `perTxLimit`
- `dailyLimit`
- `maxTxPerWindow` over `windowSeconds`
- payee allowlist (if active)
- token allowlist (if active)

### 2) Batch operations

`closeBatch(...)` and `settleBatch(...)` additionally require:

- caller is batch owner (existing rule)
- if policy enabled, caller policy must not be expired

## Policy management APIs

- `setPolicy(...)`
- `setPolicyPayee(payee, allowed)`
- `setPolicyToken(token, allowed)`
- `getPolicy(user)`
- `getPolicyUsage(user)`
- `isPolicyPayeeAllowed(user, payee)`
- `isPolicyTokenAllowed(user, token)`

## Events

- `PolicyUpdated`
- `PolicyUsageUpdated`
- `PolicyViolation(owner, target, token, reason)`
- `PolicyPayeeRuleUpdated`
- `PolicyTokenRuleUpdated`

## Frontend controls

`examples/v01-metamask-settlement.html` adds:

- policy enable/limits form
- apply/refresh buttons
- payee/token rule toggles
- policy snapshot panel with usage fields

## Known limitations in v0.1

- policy is owner-centric (per wallet), not per delegated agent identity yet
- policy usage currently tracks create-bill volume only
- dispute/resolve flows are not policy-throttled (intentionally left to next phase)
