# Karma Tokenomics v0 Draft (Settlement-First)

This draft is designed for the current product focus:

> off-chain signed intent -> on-chain settlement

The token model should strengthen this core flow, not distract from it.

## 1) Design Principle

Token utility must satisfy at least one of:

1. Increase settlement trust/safety.
2. Reduce integration cost for real users.
3. Align long-term contributor behavior with protocol growth.

If a token mechanism does not satisfy one of the above, defer it.

## 2) Recommended Token Role (v0)

### 2.1 Utility in Settlement Network

- **Staking for service operators** (API gateways, settlement relayers, indexer nodes).
- **Fee discount tier** for users/agents that hold or stake token.
- **Risk reserve participation** (future): stakers back specific settlement lanes and absorb penalties for proven misbehavior.

### 2.2 What Not To Do in v0

- Do not require token for every transaction in the first phase.
- Do not over-couple bill lifecycle correctness to token price.
- Do not launch inflation-heavy emissions before usage is real.

## 3) Value Capture Loop (Target State)

1. Real usage generates settlement/service fees.
2. Fees are split into:
   - protocol treasury,
   - operator rewards,
   - optional buyback-and-reserve policy.
3. Token demand is driven by:
   - staking access,
   - fee optimization,
   - governance over treasury/risk parameters.

Keep fee model measurable in stable units (USD/stablecoin reference) rather than token-only denomination.

## 4) Suggested Supply Framework (Template Only)

Use as placeholder planning structure, not final numbers:

- Community + ecosystem incentives
- Core contributors
- Treasury/reserve
- Strategic partners
- Public distribution (if any)

Rules to enforce:

- long cliff + linear vesting for insider allocations,
- transparent unlock calendar,
- no hidden discretionary mint powers.

## 5) Anti-Abuse Requirements

Before any incentive program goes live, include:

- anti-sybil gating for reward claims,
- wash-activity detection for fake settlement volume,
- reward caps per identity and per epoch,
- explicit slash conditions for malicious operator behavior.

## 6) Governance Scope (v0 -> v1)

Start with narrow governance:

- fee split ratio ranges,
- whitelist/registry policy parameters,
- risk reserve allocation policy.

Do not start with governance over every protocol variable.

## 7) Launch Gates (Must Pass Before Token Generation Event)

Gate A: Product and usage

- Demonstrated repeat settlement usage across independent users.
- Observable retained activity, not one-off campaign spikes.

Gate B: Security and ops

- Core contract security baseline maintained (tests/fuzz/static/formal).
- Incident response and pause procedures documented and rehearsed.

Gate C: Legal and compliance

- External legal review on jurisdiction strategy.
- Token distribution process reviewed for sanctions/AML constraints where applicable.

Gate D: Economic simulation

- Agent-based and scenario stress tests for incentive loops.
- Bear-case survival analysis (low demand, low liquidity, high volatility).

## 8) Metrics to Track During Design Phase

- Settlement volume (gross and net).
- Active agents and repeat counterparties.
- Cost per settled transaction.
- Failed settlement ratio and cause distribution.
- Concentration risk (top-1/top-5 participant share).

Only finalize token parameters after these metrics stabilize.

## 9) Minimal Roadmap

### Phase 0: No-token operation (now)

- Run protocol with direct fee model and security baseline.
- Validate real demand and workflow reliability.

### Phase 1: Token-enabled discounts/staking (design-complete)

- Introduce token as optional optimization and operator alignment layer.
- Keep settlement functional without mandatory token lock-in.

### Phase 2: Governance and reserve expansion

- Expand governance scope after operational maturity.
- Add risk reserve/slashing modules only with proven monitoring infrastructure.

## 10) Communication Template (External)

"Karma's token is designed to improve settlement reliability and network alignment.
It is introduced only after real usage, security evidence, and economic stress testing meet explicit launch gates."

