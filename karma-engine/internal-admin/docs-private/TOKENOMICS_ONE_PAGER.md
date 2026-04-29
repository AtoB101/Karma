# Karma Tokenomics — One Pager

## Positioning

Karma follows an ETH-style model: **utility-first, transparent economics, progressive decentralization**.

The token is designed to power protocol usage and security, not short-term speculation.

## What the Token Does

1. **Settlement utility**  
   Used in protocol fee flow with discount utility for network users.

2. **Security utility**  
   Operators/relayers stake tokens; provable misconduct can be slashed.

3. **Governance utility**  
   Token holders govern core economic parameters via timelocked execution.

## Economic Loop

Per settlement fee is split into three sinks:

- **40% Burn** (long-term scarcity pressure)
- **40% Reward Pool** (operator quality and network uptime)
- **20% Treasury** (audits, grants, ecosystem growth)

Core formula:

`Net Issuance = Gross Emission - Burned Amount`

Goal by stage:

- Early: controlled positive net issuance
- Growth: approach neutral
- Mature: low/near-zero or negative net issuance under high usage

## Governance Roadmap

### Phase A (0-6 months): Bootstrap
- Team multisig with full public changelog
- No hidden parameter updates

### Phase B (6-18 months): Guarded On-chain Governance
- Token voting + timelock
- Quorum and proposal thresholds enforced

### Phase C (18+ months): Community-led
- Broader delegate participation
- Reduced team control over treasury and parameters

## v0.1 Baseline Parameters (Draft)

- `FEE_BPS`: `20` (0.20%)
- `BURN_SHARE`: `40%`
- `REWARD_SHARE`: `40%`
- `TREASURY_SHARE`: `20%`
- `TIMELOCK_DELAY`: `24h+`

Guardrails:

- Fee cap and split bounds are constrained by governance policy
- Sensitive updates require longer timelock windows

## Why This Model Is Commercially Strong

- **Open protocol trust** drives integrations and adoption
- **Private operations moat** protects business differentiation
- **Transparent monthly reporting** builds long-term market confidence

Recommended boundary:

- Open source: contracts, economic rules, governance logic, public dashboards/scripts
- Private: customer-specific integrations, advanced risk models, production runbooks

## KPI Dashboard (What We Track, Not Price)

- Settlement count and volume
- Failure rate and latency
- Gross emission / burn / net issuance
- Treasury inflow/outflow
- Staking ratio and slashing events
- Governance participation and execution quality

## Go-Live Conditions

Before public token launch:

- utility is live on protocol
- burn/emission logic deployed and tested
- governance and timelock operational
- security review complete
- legal/compliance review complete

## Related Docs

- `docs/TOKENOMICS_V01.md`
- `docs/TOKENOMICS_PARAMETERS_V01.md`
