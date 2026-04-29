# Karma Tokenomics Parameters v0.1

## 0) Scope

This document defines executable parameter policy for Karma tokenomics v0.1:

- default values
- who can change what
- timelock and emergency rules
- reporting and audit requirements

This document is intended to be used with `docs/TOKENOMICS_V01.md`.

## 1) Parameter Registry

All tokenomics parameters should be stored on-chain in a dedicated config contract and emitted via events on updates.

Recommended event:

`event ParameterUpdated(bytes32 indexed key, uint256 oldValue, uint256 newValue, address indexed updater, string reason);`

Recommended key naming:

- `FEE_BPS`
- `BURN_SHARE_BPS`
- `REWARD_SHARE_BPS`
- `TREASURY_SHARE_BPS`
- `ANNUAL_EMISSION_CAP`
- `STAKING_MIN`
- `SLASH_LOW_BPS`
- `SLASH_MEDIUM_BPS`
- `SLASH_HIGH_BPS`
- `TIMELOCK_DELAY_SECONDS`

## 2) Default Values (v0.1)

### Fee and split

- `FEE_BPS = 20` (0.20%)
- `BURN_SHARE_BPS = 4000` (40%)
- `REWARD_SHARE_BPS = 4000` (40%)
- `TREASURY_SHARE_BPS = 2000` (20%)

Constraint:

- `BURN_SHARE_BPS + REWARD_SHARE_BPS + TREASURY_SHARE_BPS = 10000`

### Emission

- `ANNUAL_EMISSION_CAP = governance_defined_initial_cap`

Constraint:

- annual minted amount MUST NOT exceed cap

### Staking and slashing

- `STAKING_MIN = governance_defined_initial_stake`
- `SLASH_LOW_BPS = 100` (1%)
- `SLASH_MEDIUM_BPS = 1000` (10%)
- `SLASH_HIGH_BPS = 5000` (50%)

Constraint:

- `SLASH_LOW_BPS <= SLASH_MEDIUM_BPS <= SLASH_HIGH_BPS <= 10000`

### Governance execution

- `TIMELOCK_DELAY_SECONDS = 86400` (24h)

Constraint:

- non-emergency updates must execute through timelock only

## 3) Governance Roles

### Role A: Emergency Council (multisig)

Permissions:

- pause/unpause protocol
- trigger emergency response actions

Restrictions:

- cannot directly change tokenomics parameters unless explicitly allowed by governance policy
- every emergency action requires public postmortem within 72 hours

### Role B: Governance Executor (timelock)

Permissions:

- execute approved parameter changes after delay

Restrictions:

- cannot bypass delay for non-emergency changes

### Role C: Token Governance (voting)

Permissions:

- approve/reject proposals that alter parameters
- set emission caps and split updates within allowed bounds

Restrictions:

- proposals must include reason, impact analysis, and simulation snapshot

## 4) Change Classes and Limits

### Class 1: Low-risk operational changes

Examples:

- small fee adjustments
- small staking minimum updates

Rules:

- max change: `<= 20%` relative from current value
- timelock: minimum 24h

### Class 2: Medium-risk economic changes

Examples:

- split percentage shifts (burn/reward/treasury)
- emission cap updates

Rules:

- max change: `<= 10 percentage points` per proposal for split components
- timelock: minimum 72h
- must include simulation

### Class 3: High-risk structural changes

Examples:

- changing slashing framework
- adding/removing token utility categories

Rules:

- dedicated proposal cycle
- timelock: minimum 7 days
- requires external review summary

## 5) Proposal Template (mandatory)

Every governance proposal must include:

1. **Title and target parameters**
2. **Current value -> proposed value**
3. **Reason and expected benefit**
4. **Risk analysis**
5. **Rollback plan**
6. **Simulation or test evidence**
7. **Effective date and timelock window**

## 6) Emergency Policy

Emergency actions are limited to protecting users and protocol integrity:

- pause when exploit risk is credible
- isolate affected modules if possible
- publish incident status updates

Emergency flow:

1. Trigger pause
2. Post incident notice
3. Mitigate and test
4. Governance signoff
5. Unpause
6. Publish postmortem

## 7) Reporting Requirements

For every parameter change, publish:

- proposal ID
- vote result
- queued timestamp
- executed timestamp
- changed values
- expected vs observed outcome (in next monthly report)

Monthly report must include:

- gross emission
- burned amount
- net issuance
- treasury inflow/outflow
- staking ratio
- slashing events

## 8) Initial Guardrails (v0.1 recommendation)

Hard limits in contract/governance policy:

- `FEE_BPS` max: 100 (1.00%)
- `BURN_SHARE_BPS` min: 2000 (20%)
- `TREASURY_SHARE_BPS` max: 3000 (30%)
- `TIMELOCK_DELAY_SECONDS` min: 86400 (24h)

These limits prevent governance abuse during early stage.

## 9) Launch Readiness Checklist

Before enabling tokenomics governance:

- config contract deployed
- timelock deployed and ownership wired
- multisig signer policy finalized
- proposal template published
- reporting pipeline prepared

## 10) Versioning

- This is `TOKENOMICS_PARAMETERS_V01`.
- Any rule or default update must create a new versioned document (e.g., `V02`) and reference migration rationale.
