# Karma Core/Engine Interface Compatibility Policy v1

## Scope

This policy defines how `karma-core` (public interfaces) and
`karma-engine` (private implementations) evolve without version drift.

It applies to:

- SDK interfaces under `karma-core/sdk/basic/*`
- Engine adapters implementing those interfaces in private repositories
- Integration surfaces between protocol core and commercial engine modules

## 1. Versioning model

Use semantic versioning at two levels:

1) **Interface Package Version** (`I`): version of public interface contract.
2) **Engine Implementation Version** (`E`): version of private implementation.

Format:

- Interface: `I-MAJOR.MINOR.PATCH` (example: `I-1.2.0`)
- Engine: `E-MAJOR.MINOR.PATCH` (example: `E-3.4.1`)

Rules:

- MAJOR: breaking signature/type changes
- MINOR: backward-compatible additions
- PATCH: bug fixes, no API shape changes

## 2. Compatibility contract

Engine code MUST declare supported interface range.

Recommended manifest file in engine repo:

`internal-admin/compatibility/interface-compat.json`

Example:

```json
{
  "engineVersion": "E-3.4.1",
  "supportsInterface": {
    "min": "I-1.1.0",
    "max": "I-1.3.x"
  },
  "validatedAt": "2026-04-28T00:00:00Z"
}
```

## 3. Backward compatibility matrix

Maintain a living matrix:

| Interface (I) | Engine (E) minimum | Engine (E) maximum tested | Status |
| --- | --- | --- | --- |
| I-1.0.x | E-3.0.0 | E-3.2.x | supported |
| I-1.1.x | E-3.1.0 | E-3.4.x | supported |
| I-2.0.x | E-4.0.0 | E-4.0.x | planned |

Store and update matrix in:

- `karma-engine/docs/INTERFACE_COMPATIBILITY_POLICY_V1.md`
- optional machine-readable mirror in CI artifacts

## 4. Change control

### 4.1 Interface changes (core repo)

Any change in `karma-core/sdk/basic/interfaces.ts` MUST include:

1. Version bump proposal (`I-*`)
2. Compatibility impact note
3. Migration snippet for engine adapters
4. Mock update in `mock-risk-engine.ts` if relevant

### 4.2 Engine changes (private repo)

Any adapter change MUST include:

1. Declared supported interface range update
2. Adapter contract tests against currently supported interface version
3. Rollback note if support is narrowed

## 5. CI gates (required)

### Core CI (`karma-core/.github/workflows/core-ci.yml`)

Must fail when:

- interface file changes without policy/version note
- mock implementation is out of sync with interface types

### Engine CI (`karma-engine/.github/workflows/engine-ci.yml`)

Must fail when:

- compatibility manifest missing
- interface support range is invalid
- private adapter tests fail

## 6. Release process

1. Propose interface update in core PR.
2. Run core CI and publish new interface tag (`I-*`).
3. Update engine adapters and compatibility manifest.
4. Run engine CI against target interface tag.
5. Approve rollout and update compatibility matrix.

## 7. Emergency rollback

If production incompatibility is detected:

1. Freeze interface rollout.
2. Pin engine to last known-good interface range.
3. Re-deploy with last known-good adapter package.
4. Publish incident summary and recovery diff internally.

## 8. Security constraints

- Public core must expose interfaces/types only.
- Private repo must never publish real risk/routing/optimization algorithms.
- CI logs must not reveal proprietary decision rules or model parameters.

## 9. Ownership and review

- Core interface owners: protocol maintainers
- Engine adapter owners: private platform team
- Required reviewers for breaking changes:
  - 1 core maintainer
  - 1 engine maintainer
  - 1 security reviewer
