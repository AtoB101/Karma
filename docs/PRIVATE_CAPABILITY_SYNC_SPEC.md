# Private Capability Sync Spec (Public → Private)

> Purpose: let the private repository know exactly which private capabilities are required by the public Karma system, without leaking private logic.

## 1) How to use this spec

1. Copy the two machine-readable files below into your private repo:
   - `docs/private-sync/private_capability_manifest.v1.json`
   - `docs/private-sync/private_capability_status.v1.template.json`
2. In the private repo, create a real status file:
   - `docs/private-sync/private_capability_status.v1.json`
3. Fill `implemented`, `owner`, `evidence`, and `lastValidatedAt` for each capability.
4. Run private validation/tests and update the status file on every release.
5. Share back only the status summary (no private rules/weights/datasets) to public operators.

## 2) Required capability families

The private repo is expected to implement and maintain these families:

- receipt authenticity and anti-forgery
- execution truthfulness verification
- risk scoring and identity risk modeling
- arbitration weighting and decision assistance
- anti-abuse/anti-wash behavior controls
- responsibility loop/cycle detection enrichment
- malicious agent detection
- high-risk scenario recognition
- private operations SOP execution support

The exact checklist is in `private_capability_manifest.v1.json`.

## 3) Data sync contract

Public side should sync only:

- `capabilityId`
- `implemented` (`true/false`)
- `status` (`ready|partial|blocked`)
- `lastValidatedAt`
- `evidence` (link/path to private test/report artifact)

Public side must **not** request:

- model weights
- private threshold tables
- proprietary feature engineering
- raw private datasets
- internal reason code dictionaries

## 4) Recommended private CI gate

In private repo CI, fail release when:

- any `required: true` capability has `implemented = false`
- any required capability has no `evidence`
- `lastValidatedAt` is older than your policy window

## 5) Change management

When public architecture changes require new private capability:

1. Bump manifest version (`v1` -> `v2` when breaking).
2. Add/adjust capability items in the manifest JSON.
3. Private repo updates status file and validation evidence.
4. Release can proceed only after required capabilities are `ready`.
