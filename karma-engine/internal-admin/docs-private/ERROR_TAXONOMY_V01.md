# Error Taxonomy v0.1 (M1)

This document defines normalized error categories used by the frontend evidence export
and runtime diagnostics.

## Goals

- Keep failure reasons consistent across UI logs, JSON exports, and support workflows.
- Distinguish policy/auth failures from runtime and on-chain failures.
- Provide stable keys for downstream analytics.

## Top-level classes

- `policy_violation`: blocked by policy/budget/allowlist/rate limits.
- `authorization_error`: missing or invalid authorization/signature/nonce.
- `capacity_or_balance`: insufficient token balance, allowance, or lock capacity.
- `state_transition_error`: invalid bill/batch status transitions.
- `network_or_provider_error`: wallet/provider/network connectivity issues.
- `execution_revert`: generic contract revert where category is unknown.
- `runtime_error`: uncategorized fallback.

## Existing runtime mappings (frontend)

- `wallet_rejected` -> `authorization_error`
- `invalid_nonce` -> `authorization_error`
- `invalid_signature` -> `authorization_error`
- `unauthorized_action` -> `authorization_error`
- `allowance_or_capacity` -> `capacity_or_balance`
- `balance_insufficient` -> `capacity_or_balance`
- `invalid_state` -> `state_transition_error`
- `batch_paused` -> `state_transition_error`
- `batch_input_invalid` -> `state_transition_error`
- `contract_revert` -> `execution_revert`
- `runtime_error` -> `runtime_error`

## Policy-specific tags introduced in M1

- `policy_budget_exceeded`
- `policy_tx_amount_exceeded`
- `policy_rate_limit_exceeded`

These tags are emitted when the payment protocol enforces policy controls before bill creation.
