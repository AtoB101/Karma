# Karma Command Map V0.1 (O1.1)

## Purpose

Consolidate command entry points into clear domains so operators do not need to memorize many unrelated targets.

## Domain Entry Groups

### 1) `ops-*` (operations and diagnostics)

- `make ops-preflight` -> `scripts/preflight.sh`
- `make ops-doctor` -> `scripts/doctor.sh` (text)
- `make ops-doctor-json` -> `scripts/doctor.sh --format json`
- `make ops-support-bundle` -> `scripts/support-bundle.sh`
- `make ops-commercialization-gate` -> `scripts/commercialization-gate.sh`

### 2) `safety-*` (proof/risk/safety loop)

- `make safety-proof-gates` -> `scripts/ci-proof-gates.sh`
- `make safety-proof-patrol` -> `scripts/proof-patrol.sh`
- `make safety-guardian` -> `scripts/agent-safety-guardian.sh`
- `make safety-rule-gap-sim` -> `scripts/rule-gap-adversarial-sim.sh`

### 3) `api-*` (ecosystem integration interfaces)

- `make api-run` -> start local API server (`scripts/api_server.py`)
- `make api-smoke` -> smoke verification (`scripts/api-smoke.sh`)
- `make api-help` -> API quick command hints

## Compatibility Strategy

- Keep legacy targets for backward compatibility.
- Prefer the `ops-*`/`safety-*`/`api-*` names in docs and future automation.
- Mark old aliases as compatibility-only in command docs.
