# Migration Note: Payload Contract v1-public-testnet-prep

Change Type: Non-breaking

## Scope

Public payload contract baseline for Phase 2 testnet preparation.

## Who needs to migrate

- External integrators consuming:
  - `docs/wallet-signature-payload-examples.json`
  - `apps/agent-service-guard/templates/wallet-signature-payload-template.json`
- Internal public-repo maintainers validating integration docs.

## Required actions

1. Ensure integration code reads payload version `v1-public-testnet-prep`.
2. Align docs/runtime examples with:
   - buyer authorization payload shape
   - seller delivery attestation payload shape
3. Keep private-engine boundary endpoints unchanged:
   - `/risk/check`
   - `/dispute/recommend-resolution`
   - `/score/seller`

## Compatibility

- Backward compatibility: yes (non-breaking baseline release).
- No private scoring/anti-fraud/arbitration internals are disclosed.

## Validation checklist

- [x] `python3 scripts/phase2-public-contract-gate.py` passes
- [x] `python3 scripts/agent-service-guard-smoke.py` passes
