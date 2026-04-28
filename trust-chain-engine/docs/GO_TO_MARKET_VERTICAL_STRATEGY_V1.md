# Trust-Chain Vertical Entry Strategy V1 (Private)

Status: Draft for execution  
Scope: Private strategy only (do not mirror to public repositories)

## 1. Core thesis

Current phase objective is survival through real transaction flow, not broad protocol narrative.

North-star:

- Make AI Agents generate continuous paid calls in production-like scenarios.
- Convert protocol capability into repeated, measurable cash movement.

Primary success signal:

- Real funds settled on every successful call.

## 2. Vertical priorities (strict order)

### P0 (must execute first)

AI Agent paid API auto-settlement gateway.

One-line product:

- One API call, one automatic on-chain settlement, fully verifiable.

Why this wins now:

1. Agent tool-calling is already standard behavior.
2. Existing API payments (API key + monthly plan) do not match per-call automation.
3. Real pain exists: no reliable micro-payment, weak trust, poor settlement transparency.
4. Trust-Chain already fits: pre-authorization, post-delivery settlement, disputeability.

Initial scenarios:

- Price data API
- Model inference API
- On-chain data query API
- Trading data feed API

### P1 (after P0 proves traction)

AI Agent auto-trading / paid signal execution:

- Signal provider stakes credibility.
- Consumer pays per signal.
- Outcome-aware settlement and dispute handling.

### P2 (after P1)

On-chain API monetization toolkit (Stripe-like for API):

- Publisher creates API
- Sets per-call price
- Buyer agent calls and settles automatically

## 3. Explicit anti-scope (do not do now)

- Generic all-in-one payment protocol expansion
- DeFi settlement layer competition
- Wallet/exchange products
- Long-horizon narrative-only infrastructure work without immediate paying users

Any proposal that does not satisfy all three must be rejected:

1. High-frequency paid interactions
2. Real trust/friction problem
3. Fully automatable by Agent (minimal human intervention)

## 4. P0 product definition: AI Agent API auto-pay gateway

Core capabilities:

1. API provider registration
2. Per-call pricing configuration
3. User wallet pre-authorization
4. Agent-triggered API invocation
5. Automatic settlement after service response

## 5. MVP (extreme minimum)

Only implement these 5 capabilities:

1. Create one API (example: BTC spot price query)
2. Set call price (example: $0.01 per call equivalent)
3. User connects wallet and authorizes spending policy
4. Agent executes the call
5. Settlement happens automatically with proof artifacts

Demo storyline:

- User asks agent for BTC price
- Agent calls priced endpoint
- Endpoint returns result
- Settlement executes
- Evidence shows delivery + payment linkage

User-visible outcome:

- "One call completed, payment settled automatically, no manual billing."

## 6. Quantified success criteria (go / no-go)

Mandatory thresholds:

1. At least 1 real API provider onboarded
2. At least 10 real users
3. Real non-zero fund flow on-chain
4. Repeat usage behavior observed

If any threshold fails within the evaluation window:

- Mark phase as not successful
- Freeze scope expansion
- Enter root-cause correction loop

## 7. Two-week execution cadence (operator view)

### Week 1: ship and connect

- Finalize one production-like endpoint contract
- Wire end-to-end settlement path
- Deploy internal dashboard for call/payment visibility
- Prepare one-click demo script and evidence export

Exit criteria:

- Deterministic call -> settle path works in repeated runs
- No manual intervention in payment flow

### Week 2: real-user validation

- Onboard first provider and first 10 target users
- Run controlled paid usage sessions
- Track call count, settlement success rate, and repeat ratio
- Capture disputes/failures and feed into pricing/risk tuning

Exit criteria:

- Meets all section 6 thresholds
- Can produce an operator report with transaction proofs

## 8. Metrics board (must track daily)

- Total paid calls
- Unique paying users
- Unique providers
- Settlement success rate
- Mean settlement latency
- Average revenue per call
- Repeat usage ratio (D1, D7)
- Dispute rate and resolution latency

## 9. Risk and stop-loss gates

Stop-loss triggers:

- Settlement success rate below 95% for two consecutive days
- Dispute rate above 8% for three consecutive days
- Repeat usage ratio below 20% after initial onboarding wave

Mitigation priority:

1. Reliability first (settlement and evidence integrity)
2. Pricing simplification second
3. UX copy and onboarding third

Do not add new feature categories before reliability recovers.

## 10. Private execution boundaries

The following remain private and must stay in `trust-chain-engine`:

- Risk policy details
- Scoring models
- Routing/optimizer logic
- Fraud/anomaly detection logic
- Revenue and pricing optimization logic
- Enterprise admin operations

Public repositories may only expose capability-level interfaces and mock examples.

## 11. Immediate next actions

1. Create implementation brief: `P0_GATEWAY_EXECUTION_PLAN_V1.md`
2. Define data contracts for paid call evidence payloads
3. Add operator dashboard schema for daily metrics board
4. Prepare first provider onboarding checklist

