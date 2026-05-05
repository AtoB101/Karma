# Karma Guard for Agent Services - Roadmap

## Phase 1: Mock MVP (public repository)

- Static frontend demo for:
  - service creation
  - payment-link flow
  - mock protected orders
  - evidence hash generation
  - dispute + mock arbitration
  - dashboard + trust badge
- Public data contracts and state machine docs.
- Private risk/arbitration capabilities exposed as interface placeholders only.

## Phase 2: Testnet wallet / contract integration

- Connect buyer/seller flows to testnet wallets.
- Integrate contract events and settlement status from public contract interfaces.
- Replace mock lock status with testnet transaction-driven status updates.
- Add signature validation for buyer/seller action checkpoints.

## Phase 3: x402 / Agent API integration

- Integrate API-native payment auth flows (e.g. x402 style access control).
- Add machine-to-machine service payment flow templates.
- Standardize evidence payload publishing for external API integrators.
- Keep private risk scoring and arbitration recommendation in private engine.
