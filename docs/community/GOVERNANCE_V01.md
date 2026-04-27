# TrustChain Governance v0.1

## Objective

Create clear and fair decision flow before full decentralization.

## Governance Phases

### Phase A (current): Founder + Multisig

- founder sets direction
- multisig executes sensitive actions
- all decisions must be publicly logged

### Phase B: Community Proposal + Timelock

- proposals discussed publicly
- approved changes queued in timelock
- execution only after delay

### Phase C: Community-led

- majority of protocol decisions via token/community governance
- founder role shifts to strategy and stewardship

## Proposal Lifecycle

1. Draft proposal posted (`Discussion`)
2. Community feedback period (minimum 5 days)
3. Formal proposal (`TIP-*`)
4. Vote period (minimum 5 days)
5. Timelock queue (24h+)
6. Execution
7. Post-change report

## Proposal Classes

- `Class A` Low risk: docs/process/non-critical parameters
- `Class B` Medium risk: fee split/emission caps/config updates
- `Class C` High risk: architecture/security/economic model changes

Class B and C require stronger review and longer execution delay.

## Transparency Rules

- every approved proposal must include reason, risk, rollback plan
- every execution must publish tx hash and expected impact
- monthly summary must include executed proposals and outcomes
