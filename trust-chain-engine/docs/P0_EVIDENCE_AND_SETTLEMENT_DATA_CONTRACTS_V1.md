# P0 Evidence and Settlement Data Contracts V1 (Private)

Status: Draft for implementation  
Scope: `trust-chain-engine` only (do not publish)

Related docs:

- `docs/P0_GATEWAY_EXECUTION_PLAN_V1.md`
- `docs/INTERFACE_COMPATIBILITY_POLICY_V1.md`

## 1. Purpose

Define machine-verifiable data contracts for the P0 gateway:

1. `paid_call` event
2. `settlement` event
3. `evidence_bundle`

These contracts are the shared source of truth for:

- gateway APIs
- risk/routing/settlement engines
- analytics and dashboards
- dispute packet construction
- audit/export pipelines

## 2. Global rules (applies to all three contracts)

### 2.1 Envelope fields (required)

Every contract record MUST include:

- `schemaVersion` (string)
- `generatedAt` (RFC3339 UTC timestamp)
- `source` (string, producer identifier)
- `traceId` (string, globally unique trace reference)

Example:

```json
{
  "schemaVersion": "trustchain.p0.paid-call.v1",
  "generatedAt": "2026-04-28T18:30:00Z",
  "source": "gateway:call-executor",
  "traceId": "trace-20260428T183000Z-8f5f6f4c"
}
```

### 2.2 IDs and references

- All IDs MUST be non-empty strings.
- IDs SHOULD be immutable once written.
- Cross-object references MUST point to existing records.
- Use idempotency keys for write operations that can be retried.

### 2.3 Time and ordering

- Timestamps MUST be UTC RFC3339.
- `completedAt >= startedAt` for calls.
- `settledAt >= completedAt` when call and settlement are linked.

### 2.4 Hashes and digests

- Hash-like fields MUST be hex strings prefixed by `0x`.
- Minimum digest size: 32 bytes (`66` chars with `0x`).
- If request/response body is unavailable, field may be omitted only when explicitly marked nullable.

### 2.5 PII handling

- Do not store plaintext secrets or API keys.
- User-facing identifiers SHOULD be pseudonymous IDs.
- Wallet addresses are allowed where required for settlement proofs.

## 3. Contract A: `paid_call`

Schema name:

- `trustchain.p0.paid-call.v1`

### 3.1 Field definitions

| Field | Type | Required | Rule |
|---|---|---:|---|
| schemaVersion | string | yes | must equal `trustchain.p0.paid-call.v1` |
| generatedAt | string | yes | RFC3339 UTC |
| source | string | yes | producer id |
| traceId | string | yes | globally unique per pipeline trace |
| callId | string | yes | unique call identifier |
| providerId | string | yes | existing provider reference |
| productId | string | yes | existing priced product reference |
| userId | string | yes | internal user reference |
| agentId | string | yes | calling agent reference |
| authorizationRef | string | yes | user authorization policy reference |
| requestHash | string | yes | `0x` + 32-byte digest minimum |
| responseHash | string | yes | `0x` + 32-byte digest minimum |
| routeRef | string | yes | selected route/endpoint reference |
| riskDecisionRef | string | yes | risk evaluation record id |
| startedAt | string | yes | RFC3339 UTC |
| completedAt | string | yes | RFC3339 UTC, must be >= startedAt |
| latencyMs | integer | yes | `>= 0` |
| status | string(enum) | yes | `success|failed|timeout` |
| failureCode | string | no | required when status != success |
| idempotencyKey | string | yes | immutable retry guard |

### 3.2 Example

```json
{
  "schemaVersion": "trustchain.p0.paid-call.v1",
  "generatedAt": "2026-04-28T18:31:00Z",
  "source": "gateway:call-executor",
  "traceId": "trace-20260428T183100Z-4a7d0f9a",
  "callId": "call_01JV8Q1R4P6NN2QK4X3W7QH1ZD",
  "providerId": "provider_btc_oracle_01",
  "productId": "product_btc_spot_v1",
  "userId": "user_9f31f2a6",
  "agentId": "agent_price_assistant_v1",
  "authorizationRef": "auth_01JV8Q1K0H9Y7B2M1D3X9A8P2T",
  "requestHash": "0x9365f6b4e6fddc7b3df39d8f1c2d81269ca6cb7f8b57a3f44e5bc5ffadc4f2aa",
  "responseHash": "0x4ce18d5f4fd58bcb2d4fdb7e0d1a17b8aa5fca7be9df8fa8cb2f54f98e42e607",
  "routeRef": "route_primary_provider_btc_v1",
  "riskDecisionRef": "risk_decision_01JV8Q1R8M7A1FGT9J2V7MK6YQ",
  "startedAt": "2026-04-28T18:30:59Z",
  "completedAt": "2026-04-28T18:31:00Z",
  "latencyMs": 417,
  "status": "success",
  "idempotencyKey": "idem-call-01JV8Q1R4P6NN2QK4X3W7QH1ZD"
}
```

## 4. Contract B: `settlement`

Schema name:

- `trustchain.p0.settlement.v1`

### 4.1 Field definitions

| Field | Type | Required | Rule |
|---|---|---:|---|
| schemaVersion | string | yes | must equal `trustchain.p0.settlement.v1` |
| generatedAt | string | yes | RFC3339 UTC |
| source | string | yes | producer id |
| traceId | string | yes | globally unique trace reference |
| settlementId | string | yes | unique settlement identifier |
| callId | string | yes | existing paid_call reference |
| providerId | string | yes | provider reference |
| payerWallet | string | yes | EVM address format |
| payeeWallet | string | yes | EVM address format |
| amount | string | yes | decimal-free integer string in smallest unit |
| token | string | yes | token contract address |
| chainId | integer | yes | positive integer |
| txHash | string | no | required when status in `confirmed|failed|disputed` |
| txNonce | integer | no | optional, if chain tx submitted |
| settlementPolicyRef | string | yes | settlement policy snapshot id |
| settledAt | string | no | required when status != pending |
| status | string(enum) | yes | `pending|confirmed|failed|disputed` |
| failureCode | string | no | required when status == failed |
| disputeRef | string | no | required when status == disputed |
| idempotencyKey | string | yes | immutable retry guard |

### 4.2 Example

```json
{
  "schemaVersion": "trustchain.p0.settlement.v1",
  "generatedAt": "2026-04-28T18:31:03Z",
  "source": "gateway:settlement-commit",
  "traceId": "trace-20260428T183100Z-4a7d0f9a",
  "settlementId": "set_01JV8Q2A2ZX9E8AT2Q8D92V7NB",
  "callId": "call_01JV8Q1R4P6NN2QK4X3W7QH1ZD",
  "providerId": "provider_btc_oracle_01",
  "payerWallet": "0x1111111111111111111111111111111111111111",
  "payeeWallet": "0x2222222222222222222222222222222222222222",
  "amount": "10000",
  "token": "0x3333333333333333333333333333333333333333",
  "chainId": 11155111,
  "txHash": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "txNonce": 391,
  "settlementPolicyRef": "policy_settlement_p0_v1",
  "settledAt": "2026-04-28T18:31:03Z",
  "status": "confirmed",
  "idempotencyKey": "idem-set-01JV8Q2A2ZX9E8AT2Q8D92V7NB"
}
```

## 5. Contract C: `evidence_bundle`

Schema name:

- `trustchain.p0.evidence-bundle.v1`

### 5.1 Field definitions

| Field | Type | Required | Rule |
|---|---|---:|---|
| schemaVersion | string | yes | must equal `trustchain.p0.evidence-bundle.v1` |
| generatedAt | string | yes | RFC3339 UTC |
| source | string | yes | producer id |
| traceId | string | yes | must link call and settlement lineage |
| evidenceId | string | yes | unique evidence identifier |
| callId | string | yes | existing paid_call reference |
| settlementId | string | yes | existing settlement reference |
| requestDigest | string | yes | `0x` + 32-byte digest minimum |
| responseDigest | string | yes | `0x` + 32-byte digest minimum |
| authorizationRef | string | yes | user authorization reference |
| riskDecisionRef | string | yes | risk decision reference |
| routeRef | string | yes | route decision reference |
| settlementTxHash | string | no | required when settlement confirmed/failed/disputed |
| disputeRef | string | no | required when settlement status disputed |
| artifactUris | array<string> | no | optional pointers to exported artifacts |
| integrityProof | object | yes | hash-chain/signature metadata |
| createdAt | string | yes | RFC3339 UTC |

### 5.2 `integrityProof` object

Required subfields:

- `proofType` (`hash-chain|signature|hash-chain+signature`)
- `payloadHash` (`0x...`)
- `manifestDigest` (`0x...`)
- `signer` (address or service key id)
- `signedAt` (RFC3339 UTC, nullable only if unsigned mode explicitly enabled)

### 5.3 Example

```json
{
  "schemaVersion": "trustchain.p0.evidence-bundle.v1",
  "generatedAt": "2026-04-28T18:31:05Z",
  "source": "gateway:evidence-writer",
  "traceId": "trace-20260428T183100Z-4a7d0f9a",
  "evidenceId": "evd_01JV8Q2CZ6E0Q8FM7BPS9KJ4QW",
  "callId": "call_01JV8Q1R4P6NN2QK4X3W7QH1ZD",
  "settlementId": "set_01JV8Q2A2ZX9E8AT2Q8D92V7NB",
  "requestDigest": "0x9365f6b4e6fddc7b3df39d8f1c2d81269ca6cb7f8b57a3f44e5bc5ffadc4f2aa",
  "responseDigest": "0x4ce18d5f4fd58bcb2d4fdb7e0d1a17b8aa5fca7be9df8fa8cb2f54f98e42e607",
  "authorizationRef": "auth_01JV8Q1K0H9Y7B2M1D3X9A8P2T",
  "riskDecisionRef": "risk_decision_01JV8Q1R8M7A1FGT9J2V7MK6YQ",
  "routeRef": "route_primary_provider_btc_v1",
  "settlementTxHash": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "artifactUris": [
    "s3://tc-private-artifacts/evidence/evd_01JV8Q2CZ6E0Q8FM7BPS9KJ4QW/payload.json",
    "s3://tc-private-artifacts/evidence/evd_01JV8Q2CZ6E0Q8FM7BPS9KJ4QW/manifest.json"
  ],
  "integrityProof": {
    "proofType": "hash-chain+signature",
    "payloadHash": "0x6bd96f0e4f29adbd0208d0ed1a8f0db55f8f39f55f0afdb2f4af2c33e484f8b7",
    "manifestDigest": "0xb798f36d9f50de6f2fbe26157f3b6584d1f23cc2dca33d7d6ab0d7de7f4e8cf2",
    "signer": "0x4444444444444444444444444444444444444444",
    "signedAt": "2026-04-28T18:31:05Z"
  },
  "createdAt": "2026-04-28T18:31:05Z"
}
```

## 6. Validation rules

## 6.1 Hard validation

Reject record if:

1. missing any required field
2. schemaVersion mismatch
3. malformed timestamps
4. invalid digest/address format
5. broken references (`callId`, `settlementId`, etc.)

## 6.2 Stateful validation

Apply sequence checks:

1. `paid_call.status=success` should be prerequisite for `settlement.status=confirmed` in normal path.
2. one `callId` must map to at most one terminal successful settlement.
3. evidence trace (`traceId`) must remain consistent across call -> settlement -> evidence.

## 6.3 Idempotency validation

`idempotencyKey` must be unique for logical action type:

- call execution action keyspace
- settlement commit action keyspace

Retries MUST return same logical record identity when key already exists.

## 7. Versioning and compatibility

Follow semantic policy from `INTERFACE_COMPATIBILITY_POLICY_V1.md`:

- Add optional fields: minor version bump
- Remove/change meaning/type of existing field: major version bump
- Clarification with no data shape change: patch version update in docs

Compatibility guarantees:

1. readers must tolerate unknown fields
2. writers must not silently change required field semantics
3. migration scripts required for major upgrades

## 8. Storage and retention policy (P0 baseline)

Minimum retention:

- paid_call: 90 days hot + 1 year cold
- settlement: 1 year hot + 3 years cold
- evidence_bundle: 1 year hot + 5 years cold (audit path)

Immutability:

- evidence bundles should be write-once append-only
- corrections recorded via superseding records, not in-place overwrite

## 9. Security and access policy

Access tiering:

1. ops dashboard: aggregated, redacted views
2. dispute operators: full evidence access for assigned cases
3. auditors: read-only signed export packages

Never include:

- raw private keys
- API secrets
- plaintext auth tokens

## 10. Conformance checklist

Each producer service must pass:

- [ ] JSON schema conformance test
- [ ] reference integrity test
- [ ] idempotency replay test
- [ ] timestamp ordering test
- [ ] digest/address format test
- [ ] redaction and secret scan test

Each consumer service must pass:

- [ ] unknown-field tolerance test
- [ ] version compatibility test
- [ ] missing optional field tolerance test

## 11. Implementation next steps

1. Generate formal JSON Schema files for all three contracts under:
   - `internal-admin/contracts/p0/`
2. Add CI check to validate sample payloads against schemas.
3. Add reconciliation job:
   - paid_call ledger vs settlement ledger parity check.
4. Add daily contract health report to internal dashboard.
