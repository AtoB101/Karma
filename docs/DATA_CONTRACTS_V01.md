# Karma Output Data Contracts V0.1

## Goal

Define a shared machine-readable contract baseline for operational JSON artifacts so every output is traceable, versioned, and consistently auditable.

## Required Top-Level Fields

All core JSON outputs MUST include:

- `schemaVersion`: contract identifier and version, e.g. `karma.guardian.v1`
- `generatedAt`: UTC timestamp in ISO8601 (`YYYY-MM-DDTHH:MM:SSZ`)
- `source`: producer identifier (`script:<name>` or `api:<name>`)
- `traceId`: correlation ID for cross-artifact tracing

## Contract Families (v0.1)

- Guardian report: `karma.guardian.v1`
- Guardian alarm: `karma.guardian.alarm.v1`
- Risk register: `karma.risk.register.v1`
- Proof patrol alert: `karma.proof.patrol.alert.v1`
- Proof batch summary: `karma.proof.batch.v1`
- Commercial readiness gate: `karma.commercial.gate.v1`

## Backward Compatibility

Legacy fields are retained for compatibility:

- `version`
- existing domain-specific payload structures

Consumers SHOULD migrate to `schemaVersion` as the canonical parser switch.

## Validation

Use:

```bash
make validate-output-contracts
```

This gate validates latest generated outputs under `results/` and fails if required contract fields are missing.
