# Migration note — payload `v1-public-testnet-prep`

## Migration Summary

Public wallet-signature payload version for testnet integration prep.
Aligned with `docs/wallet-signature-payload-examples.json` and `docs/integration-guide.md`.

## Required Actions

- Keep `Payload Version: v1-public-testnet-prep` in sync across integration docs and examples JSON.
- Use `apps/console` as the public web surface (Agent Guard templates removed).
- Validate with `python3 scripts/phase2-public-contract-gate.py`.

## Compatibility Impact

Non-breaking for existing example shapes (`buyer_authorize_payment`, `seller_delivery_attestation`).
On-chain settlement path is **KarmaBilateral** only.

## Rollback Plan

Revert examples JSON `version` and integration-guide version markers together; re-run phase2 gate.
