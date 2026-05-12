# Security Ops Drill Runbook (Redis / Transition Flood / Auto-Brake)

This runbook defines the operations-grade drills for the hardened security controls.

## Scope

The drill suite validates three high-risk control paths:

1. Redis outage injection and `fail-open`/`fail-closed` boundaries.
2. Malicious settlement transition flood detection and alerting.
3. Auto-brake robustness against false positives and control-path false negatives.

## Preconditions

- Test environment with API test dependencies installed.
- No production credentials are required.
- Runtime should be able to execute `pytest` locally.

## Drill Command

```bash
pytest -q tests/unit/test_ops_security_drills.py
```

## Expected Outcomes

### 1) Redis outage boundary drill

`test_ops_drill_rate_limit_fail_modes`

- In production mode, sensitive keys (`state_transition`, `write_sensitive`) fail closed with `503`.
- Non-sensitive keys (e.g. `default`) remain fail open.
- In development mode, sensitive keys remain fail open to preserve local operability.

### 2) Malicious transition flood drill

`test_ops_drill_transition_flood_emits_critical_denied_rate_alert`

- Repeated invalid transitions trigger high denied counts.
- Security report includes both:
  - `settlement_transition_denied_spike`
  - `settlement_transition_denied_rate`
- Alert dimensions include offender actor ID for triage.

### 3) Auto-brake robustness drills

`test_ops_drill_auto_brake_false_positive_is_blocked`

- A mixed sequence with low denied-rate must **not** trigger safety mode.

`test_ops_drill_auto_brake_false_negative_control_path`

- A critical denied-rate alert appears, but when `auto_brake_on_transition_critical=false`, safety mode remains disabled (control-path validation).

## Operational Use

- Run this suite before security policy changes, before release candidates, and after any edits to:
  - settlement transition guards,
  - runtime safety controls,
  - rate-limit middleware,
  - security alert policy thresholds.

## Incident Follow-Up

If any drill fails:

1. Treat as a release blocker.
2. Capture test output and the failing control path.
3. Update `docs/SECURITY_INCIDENT_PLAYBOOK.md` actions if response flow changes.
4. Re-run this drill suite and `scripts/public-beta-security-gate.sh` after fixes.
