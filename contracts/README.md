# Contracts directory (public mapping)

Canonical Solidity for this repository lives under **`contracts/`**.

| Conceptual name (docs / product) | Engineering source of truth |
|----------------------------------|--------------------------------|
| Bill lifecycle + settlement + dispute surface | `contracts/core/NonCustodialAgentPayment.sol` |
| EIP-712 quote settlement | `contracts/core/SettlementEngine.sol` |
| Auth token consumption | `contracts/core/AuthTokenManager.sol` |
| DID registry | `contracts/core/KYARegistry.sol` |
| Circuit breaker | `contracts/core/CircuitBreaker.sol` |

**Do not** introduce parallel `KarmaSettlement.sol` / `KarmaRegistry.sol` stacks in the public repository without a
governance decision and migration plan — they would duplicate settlement authority and violate the single golden path.
