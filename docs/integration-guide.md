# Karma Integration Guide (Public)

This guide describes how external developers integrate with Karma’s public
settlement + evidence surface (console, wallet payloads, bilateral contracts).

## Version markers

- Payload examples version: `v1-public-testnet-prep`
- Active settlement contract: `KarmaBilateral`

## Integration model

Karma protects agent commerce with:

- owner capacity lock + agent spend limits
- bilateral escrow bind / settle
- delivery verification + evidence
- dispute / settlement reputation hooks

Public repo exposes:

- `apps/console` operator UI
- public API + Python/TS SDKs
- on-chain `karma-core/contracts/core/KarmaBilateral.sol`
- wallet signature payload examples

Private risk-scoring engines remain out of scope.

## Public web surface (current)

- `apps/console/` — primary owner/operator console (wallet, capacity, orders, evidence)

## Phase 2 public preparation package

For testnet integration preparation, use:

- Payload Version: `v1-public-testnet-prep`
- `docs/testnet-integration-checklist.md`
- `docs/wallet-signature-payload-examples.json`
- Migration notes (required when introducing breaking payload changes): `docs/migrations/<payload-version>.md`

These are public-safe templates and checklists only.
