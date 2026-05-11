# Contracts directory (public mapping)

Canonical Solidity for this repository lives under **`karma-core/contracts/`**, not under this top-level `contracts/`
folder.

| Conceptual name (docs / product) | Engineering source of truth |
|----------------------------------|--------------------------------|
| Bill lifecycle + settlement + dispute surface | `karma-core/contracts/core/NonCustodialAgentPayment.sol` |
| EIP-712 quote settlement | `karma-core/contracts/core/SettlementEngine.sol` |
| Auth token consumption | `karma-core/contracts/core/AuthTokenManager.sol` |
| DID registry | `karma-core/contracts/core/KYARegistry.sol` |
| Circuit breaker | `karma-core/contracts/core/CircuitBreaker.sol` |

**Do not** introduce parallel `KarmaSettlement.sol` / `KarmaRegistry.sol` stacks in the public repository without a
governance decision and migration plan — they would duplicate settlement authority and violate the single golden path.
