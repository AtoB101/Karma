# Contributing to Karma

Thank you for improving Karma.

This repository accepts public contributions under a clear licensing and
brand-protection policy.

## Before you open a PR

1. Read `LICENSE` (AGPL-3.0-only community license).
2. Read `docs/LICENSING.md` (community + commercial licensing model).
3. Read `TRADEMARK_POLICY.md` (brand and naming restrictions).
4. Ensure your change does not leak private operational or security parameters.

## Contribution workflow

1. Fork the repository and create a feature branch.
2. Keep changes scoped and include tests/docs updates when relevant.
3. Run local checks before opening a PR.
4. Open a PR with a concise summary and validation steps.

## Local checks (Python API + tests)

Install dev dependencies and run the **full** pytest tree (unit, integration, and
root-level tests under `tests/`, including Runtime Gateway E2E in
`tests/integration/test_runtime_e2e.py`):

```bash
pip install -e ".[dev]"
pytest tests/ -q
# or: make test-python
```

Contract / static analysis may use `forge test` and repo scripts as documented in
`README.md` and `.github/workflows/`.

## Contract changes that affect the private runtime

If your PR changes **`openapi/karma-v1.yaml`**, **`core/schemas.py`** verify/apply-verification payloads, or related HTTP contracts, add the trigger line from **`docs/SYNC_PRIVATE_RUNTIME.md`** to the PR description (and changelog when applicable) so private Karma2 can bump **`PUBLIC_BASELINE_*`** and run contract tests. See that file for the exact sentence and playbook link.

## Payload contract PRs (Karma Guard / Phase 2)

If your PR adds **`Change Type: Breaking`** to `docs/agent-service-guard-changelog.md`,
CI requires:

- `docs/migrations/<payload-version>.md` with the sections enforced by
  `scripts/phase2-public-contract-gate.py`
- A PR description section with heading **`## Migration Impact`** or
  **`### Migration Impact`** (rollout, integrator steps; link the migration doc)

## Developer certificate and licensing of contributions

By submitting a contribution (pull request, patch, commit, or issue attachment),
you represent that:

1. You have the legal right to submit the contribution.
2. The contribution is your original work, or you have proper permission to use
   and submit it.
3. You agree that the maintainers may distribute your contribution under this
   repository's licensing framework:
   - Community/open-source distribution under the root `LICENSE` (AGPL-3.0-only)
   - Commercial distribution under separate commercial terms described in
     `docs/LICENSING.md`
4. You understand that code license and trademark rights are separate, and
   project names/logos are governed by `TRADEMARK_POLICY.md`.

If you cannot agree to these terms, do not submit contributions.

## Security and responsible disclosure

Do not open public issues for exploitable security vulnerabilities.
Use the private disclosure path in `SECURITY.md`.
