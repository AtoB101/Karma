# Karma Tokenomics v0.1 (Draft)

## 0) Purpose

This document defines a practical, ETH-style tokenomics baseline for Karma:

- utility first, speculation second
- transparent issuance and value sink
- progressive decentralization with clear governance handoff

This is a product/economic design draft, not legal advice.

## 1) Design Principles

1. **Protocol-first utility**  
   The token must be required for protocol participation (fees, staking, governance), not only for trading.

2. **Credible neutrality**  
   Rules are explicit and auditable on-chain, with predictable parameter change process.

3. **Sustainable issuance**  
   Emissions are budgeted and tied to measurable contributions.

4. **Value feedback loop**  
   Protocol usage should produce burn and/or treasury inflow.

5. **Gradual decentralization**  
   Governance transitions from multisig -> timelock governance -> broader DAO.

## 2) Token Utility (must-have)

Karma token should have all three functions:

1. **Settlement fee utility**
   - users pay settlement fee in supported token mode
   - paying in Karma token receives fee discount

2. **Staking and security utility**
   - operators/relayers stake tokens
   - protocol can slash stake for provable misconduct (fraud, replay abuse, policy violations)

3. **Governance utility**
   - token voting controls selected protocol parameters
   - sensitive actions gated by timelock

## 3) Economic Flow

Per-settlement fee (example):

- total fee = `settlement_amount * fee_bps / 10_000`

Suggested default allocation:

- `40%` -> burn
- `40%` -> operator/reward pool
- `20%` -> protocol treasury

Rationale:
- burn supports long-term scarcity pressure
- operator rewards support network quality and uptime
- treasury funds grants, audits, and ecosystem growth

## 4) Emission Policy (v0.1 recommendation)

Use capped annual emission budget with governance limits.

- `annual_emission_cap` set by governance (timelock protected)
- emissions distributed to:
  - operator incentives
  - developer/community grants
  - ecosystem bootstrap programs

Net inflation formula:

`net_issuance = gross_emission - burned_amount`

Target policy:

- early stage: positive but controlled net issuance
- growth stage: approach neutral
- mature stage: aim for low/near-zero or negative net issuance during high usage periods

## 5) Governance Rollout (3 phases)

### Phase A - Bootstrap (0-6 months)

- governance by team multisig
- mandatory public changelog for every parameter change
- no hidden admin actions

### Phase B - Guarded On-chain Governance (6-18 months)

- add token voting + timelock execution
- define quorum and proposal thresholds
- emergency pause remains limited and transparent

### Phase C - Community-led Governance (18+ months)

- broaden voter base and delegate model
- reduce direct team control
- treasury disbursement increasingly governed on-chain

## 6) Parameter Set for v0.1

Initial parameters (draft starting point):

- `fee_bps`: 20 (0.20%)
- `burn_share`: 40%
- `reward_share`: 40%
- `treasury_share`: 20%
- `staking_min`: governance-defined fixed minimum
- `slashing_range`: governance-defined by violation class
- `timelock_delay`: 24-72h for non-emergency actions

All parameter updates should emit events and be included in monthly disclosures.

## 7) Metrics That Matter (not price-first)

Primary protocol metrics:

- settlement count (daily/weekly/monthly)
- settled volume
- failed settlement rate
- active integrators
- active operators
- median settlement latency

Economic metrics:

- gross emission
- burned amount
- net issuance
- treasury inflow/outflow
- staking ratio (% of circulating supply staked)

Governance metrics:

- proposals submitted/passed/executed
- turnout and concentration
- average execution delay

## 8) Monthly Transparency Report Template

Use this template each month:

1. **Protocol activity**
   - settlement count
   - volume
   - failure rate

2. **Token economics**
   - gross emission
   - burned amount
   - net issuance
   - treasury balance change

3. **Security and operations**
   - incidents
   - pause/unpause events
   - slashing events

4. **Governance**
   - proposal list and status
   - parameter changes and reasons

5. **Roadmap updates**
   - completed milestones
   - next-month priorities

## 9) Open Source vs Private Boundary

Recommended open-source scope:

- tokenomics formulas and parameter definitions
- smart contracts and tests
- governance mechanism contracts
- public dashboards/scripts for transparency reporting

Keep private (commercial moat):

- customer-specific integration logic
- advanced risk scoring internals
- private monitoring runbooks and escalation procedures

## 10) Risks and Controls

1. **Over-emission risk**
   - control: hard annual cap + timelock changes

2. **Governance capture risk**
   - control: quorum rules, delegation transparency, phased decentralization

3. **Operator centralization risk**
   - control: lower entry barriers, reward curve design, slash enforcement

4. **Compliance/regulatory risk**
   - control: legal review before token launch and before major model changes

## 11) Implementation Roadmap

### Step 1 (now)

- align internal team on utility + fee split + governance phases
- finalize this document as v1.0 internal baseline

### Step 2 (protocol integration)

- implement fee split accounting and burn/reward/treasury routing
- implement staking/slashing scaffolding
- add governance config storage with events

### Step 3 (testnet economics)

- run simulation and testnet pilot
- validate incentives and failure behavior under stress

### Step 4 (public launch prep)

- external security review
- public docs + dashboard + monthly report process
- legal/compliance signoff

## 12) Decision Checklist (Go/No-Go)

Before public token launch, all must be true:

- utility is live in protocol (not only roadmap)
- emission and burn logic deployed and tested
- governance process documented and operational
- monthly transparency process ready
- legal and security reviews completed

---

If this draft is accepted, next suggested artifact is:

- `docs/TOKENOMICS_PARAMETERS_V01.md` (exact values, formulas, and change policy)
