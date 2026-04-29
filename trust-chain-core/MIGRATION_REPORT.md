# Trust-Chain Split Report (Core/Public + Engine/Private)

## 1) New directory structure

- `trust-chain-core/` (public)
  - `contracts/`
  - `sdk/basic/`
  - `docs/public/`
  - `examples/`
  - `README.md`
  - `LICENSE`
- `trust-chain-engine/` (private)
  - `risk-engine/`
  - `settlement-optimizer/`
  - `routing-engine/`
  - `dispute-engine/`
  - `analytics-engine/`
  - `enterprise-dashboard/`
  - `internal-admin/`
  - `data-pipeline/`
  - `pricing-strategy/`

## 2) Files retained in public repository (`trust-chain-core`)

- `contracts/**` (base settlement contracts, interfaces, tests)
- `sdk/basic/interfaces.ts` (public extension interfaces)
- `sdk/basic/mock-risk-engine.ts` (mock only)
- `docs/public/GET_STARTED.md`
- `docs/public/TROUBLESHOOTING.md`
- `docs/public/V0_1_SCOPE.md`
- `docs/public/V0_1_CLIENT_TEMPLATE.md`
- `examples/v01-metamask-settlement.html`
- `examples/v01-quote-settlement.ts`
- `README.md`
- `LICENSE`

## 3) Files moved to private repository (`trust-chain-engine`)

- Risk/monitoring/alert/strategy operations docs and scripts
- Batch optimization demos and related artifacts
- Internal deployment and runbook tooling
- Current moved content root:
  - `trust-chain-engine/internal-admin/docs-private/`
  - `trust-chain-engine/internal-admin/scripts-private/`
  - `trust-chain-engine/internal-admin/core-devops/`
  - `trust-chain-engine/settlement-optimizer/examples-private/`
  - `trust-chain-engine/internal-admin/artifacts/results/`

## 4) Files requiring deletion or desensitization in public

- Public root `.env.example` removed from core, retained as private template in:
  - `trust-chain-engine/internal-admin/core-devops/.env.example.template`
- Public docs no longer include internal strategy details.
- Public README now provides only high-level capability statements.

## 5) Modules converted to interface-only access

- `RiskEngine` access model in public SDK:
  - Interface: `sdk/basic/interfaces.ts`
  - Mock implementation: `sdk/basic/mock-risk-engine.ts`
  - Real implementations must exist only in `trust-chain-engine/risk-engine/`

## 6) Final security checklist

- [x] `.env` not committed in public core root
- [x] no real private key values detected in public files
- [x] no API key values detected in public files
- [x] no RPC secret values detected in public files
- [x] strategy/risk/monitoring scripts moved to private engine
- [x] public README stripped of strategy details
- [x] public docs constrained to onboarding/protocol baseline

## 7) Forward policy

All future modules involving risk control, data intelligence, routing, optimization,
revenue models, enterprise admin, and strategy decisions must be implemented
in `trust-chain-engine` only and must not be merged into `trust-chain-core`.

## 8) Separate-remote publishing (confirmed step)

Use the release helpers under repo root:

- `split-release/publish-core.sh` (publish `trust-chain-core/` to public remote)
- `split-release/publish-engine.sh` (publish `trust-chain-engine/` to private remote)
- guide: `split-release/README.md`

Example:

```bash
./split-release/publish-core.sh git@github.com:<org>/trust-chain-core.git main
./split-release/publish-engine.sh git@github.com:<org>/trust-chain-engine.git main
```
