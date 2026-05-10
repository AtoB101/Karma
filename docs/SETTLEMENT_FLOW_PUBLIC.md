# Settlement flow (public)

Canonical on-chain settlement for bills is implemented in:

- `karma-core/contracts/core/NonCustodialAgentPayment.sol`

High-level public states (informative — refer to source for exact enums):

- Funds may be **locked** by parties  
- A **bill** is created with `proofHash` / `scopeHash` references  
- Buyer may **confirm** or flows may move to **dispute** / **expire** per contract rules  
- **Payout** is requested through the existing payout path after confirmation  

Direct quote settlement (non-bill path) is implemented in:

- `karma-core/contracts/core/SettlementEngine.sol`

This repository **does not** ship a second parallel settlement contract named `KarmaSettlement.sol`; product docs may use
that label conceptually, but engineering should map to the files above.
