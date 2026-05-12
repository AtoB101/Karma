# Ecosystem SDK One-Click Deployment

This repository now includes a one-click integration path for:

- OpenClaw developers
- OpenManus developers

## CLI

The entrypoint is:

```bash
karma-ecosystem --framework <openclaw|openmanus> <init|deploy|verify|doctor|bootstrap>
```

Common flags:

- `--workspace-dir <path>`
- `--runtime-url <url>`
- `--agent-id <id>`
- `--api-key <karma_key>`
- `--overwrite`
- `--skip-runtime-check`
- `--release-templates` (for `deploy`)

## Generated scaffold

`init` creates:

- `.env.karma.example`
- `karma.ecosystem.json`
- framework specific adapter file:
  - `openclaw/karma.integration.yaml`
  - `openmanus/karma.integration.toml`

## Recommended flow

```bash
# 1) generate scaffold
karma-ecosystem --framework openclaw init --workspace-dir .

# 2) verify env/runtime
karma-ecosystem --framework openclaw doctor --workspace-dir .

# 3) deploy (scaffold + doctor)
karma-ecosystem --framework openclaw deploy --workspace-dir .

# 4) release-grade bootstrap (Docker/env-inject/CI template)
karma-ecosystem --framework openclaw bootstrap --workspace-dir . --skip-runtime-check
```

## Bootstrap artifacts

`bootstrap` (or `deploy --release-templates`) additionally creates:

- `deploy/karma-ecosystem/docker-compose.<framework>.yml`
- `scripts/karma-ecosystem-inject-env.sh`
- `.github/workflows/karma-ecosystem-verify.template.yml`

You can then materialize runtime env quickly:

```bash
bash scripts/karma-ecosystem-inject-env.sh .
```

`verify` and `doctor` both return machine-readable JSON for CI pipelines.
