# Cross-Repository Deployment Playbook (Karma + Karma2)

This playbook is the operational standard for deploying with a public core repo
(`Karma`) and a private engine repo (`Karma2`).

## Goals

- Keep private logic out of the public repository.
- Keep deployment linkage deterministic and auditable.
- Make rollback possible with one manifest file.

## Required Inputs

Before deployment, prepare:

1. Core release tag and commit from `Karma`
2. Core on-chain addresses (per environment)
3. Engine release tag and commit from `Karma2`
4. One deployment manifest JSON (see `split-release/templates/`)
5. One core version lock file in `Karma2` (`CORE_VERSION.lock`)

## Standard Flow

### Step 1: Freeze core version (public repo)

In `Karma`:

- merge approved PRs
- create release tag (example: `core-v1.6.0`)
- record commit SHA
- produce deployment artifacts (addresses, ABI hash if used)

### Step 2: Lock engine to core (private repo)

In `Karma2`:

- update `CORE_VERSION.lock` using the released core tag/SHA
- update engine code/config to that exact core contract surface
- run private integration tests against locked core version

### Step 3: Build deployment manifest

Create `deployment-manifest.json` from template:

- include environment (`sepolia`/`mainnet`)
- include core and engine versions/commits
- include contract addresses and release owner

### Step 4: Validate manifest and lock alignment

Run:

```bash
./split-release/validate-manifest.sh \
  --manifest /path/to/deployment-manifest.json \
  --core-lock /path/to/CORE_VERSION.lock
```

This blocks release if required fields are missing or versions mismatch.

### Step 5: Deploy sequence

1. Deploy/verify core contracts (if changed)
2. Deploy/rollout engine services
3. Run cross-repo smoke checks
4. Record final tx hashes + timestamps in manifest

### Step 6: Go/No-Go checkpoint

Go only if:

- public repo checks green
- private repo checks green
- manifest validated
- owner approval recorded

## Rollback Standard

Rollback uses the previous manifest:

1. identify last known good manifest
2. revert engine to previous `engine.commit`
3. if needed, point engine config to previous core addresses
4. run smoke checks again
5. publish incident + rollback note internally

## Minimal CI Recommendation

In private repo CI (`Karma2`):

- validate `CORE_VERSION.lock` presence
- validate manifest schema
- verify `core.version` in manifest == `core.version` in lock file

