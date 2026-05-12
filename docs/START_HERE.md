# KARMA Start Here

If this is your first time in the repository, use this page as the entry point.

## What this repo is

KARMA is a trust-and-settlement system for AI agent workloads:
- verifiable execution receipts and evidence bundles
- settlement/dispute lifecycle APIs
- non-custodial settlement contracts
- operational safety controls and security monitoring

## 30-second orientation

1. Read the top-level architecture and run flow: `README.md`
2. Pick your role path below.

---

## Role-based quick paths

### A) Backend/API developer

1. `docs/GETTING_STARTED.md`
2. `docs/API_REFERENCE.md`
3. `api/`, `core/`, `db/`, `services/`, `worker/`
4. `tests/integration/test_api.py`

### B) Contract/security engineer

1. `contracts/core/`
2. `contracts/test/`
3. `foundry.toml`
4. `certora/README.md`
5. `docs/SECURITY_RELEASE_GATES.md`

### C) Runtime/SDK integrator

1. `docs/AGENT_INTEGRATION.md`
2. `docs/EXECUTION_RECEIPT_STANDARD.md`
3. `sdk/`, `agents/`, `trusted_agent_runtime/`
4. `examples/demo_captioning.py`

### D) Security / SRE / operations

1. `docs/SECURITY_INCIDENT_PLAYBOOK.md`
2. `docs/SECURITY_RELEASE_GATES.md`
3. `docs/SECURITY_OPS_DRILL_RUNBOOK.md`
4. `tests/unit/test_ops_security_drills.py`

### E) Contributor / reviewer

1. `CONTRIBUTING.md`
2. `SECURITY.md`
3. `TRADEMARK_POLICY.md`
4. `docs/LICENSING.md`

---

## Minimal local validation

```bash
python3 -m pytest -q tests/unit tests/integration/test_api.py
```

For contract verification, use Foundry:

```bash
forge build
forge test -vv
```
