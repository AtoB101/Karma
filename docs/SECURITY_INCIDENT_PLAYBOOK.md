# Security Incident Playbook

This playbook defines the minimum response workflow for security incidents during public beta.

## 1) Trigger Conditions

Treat any of the following as an incident trigger:

- Repeated `auth_failure_spike` alerts from `/v1/security/ops/alerts`
- Sustained `rate_limit_spike` with customer-facing 429 impact
- `private_runtime_error_rate` alert at `high` or `critical`
- baseline drift alerts (`*_baseline_drift`) sustained across consecutive windows
- Any confirmed unauthorized write action, credential leak, or data integrity violation

## 2) Severity Levels

- **SEV-1 (critical)**: active compromise, unauthorized settlement/state transition, widespread outage with security implications.
- **SEV-2 (high)**: strong attack signals or persistent degradation that could lead to compromise.
- **SEV-3 (medium)**: suspicious trend requiring containment and monitoring.

## 2.1) Alert Escalation Mapping

Use `/v1/security/ops/alerts` response fields:

- `escalation.level = page`: immediate on-call paging (treat as SEV-1/SEV-2 depending blast radius).
- `escalation.level = watch`: active monitoring with named owner (SEV-2/SEV-3).
- `suppressed_alert_count > 0`: recurring signal is still active; do not treat as resolved.

## 3) Immediate Response (0-15 minutes)

1. Open incident channel and assign roles:
   - Incident Commander
   - API/Runtime Operator
   - Forensics Recorder
2. Capture immutable context:
   - Request IDs from security audit logs
   - Affected endpoints, actor IDs, and time window
   - Current `/v1/security/ops/alerts` snapshot
3. Execute first containment:
   - Rotate exposed `AUTH_API_KEYS`
   - Increase rate-limit strictness if abuse is active
   - Temporarily disable risky public entrypoints if required

## 4) Investigation and Containment

- Correlate `security_write_audit` logs with auth failures and 429 spikes.
- Validate whether private runtime failures are dependency/network or malicious traffic amplification.
- If compromise suspected:
  - Force key rotation (`APP_SECRET_KEY`, runtime keys, API keys)
  - Revoke affected agent credentials
  - Isolate compromised workers/services

## 5) Recovery

- Restore services incrementally with heightened monitoring.
- Confirm:
  - auth failure volume normalized
  - 429 ratios normalized
  - private runtime error rate below threshold
- Confirm `suppressed_alert_count == 0` for at least one full alert window after mitigation.
- Run `scripts/public-beta-security-gate.sh` before declaring incident resolved.

## 6) Post-Incident Review

Within one cycle after resolution:

- Publish timeline (trigger, detection, containment, recovery)
- Record root cause and blast radius
- Add concrete preventive actions with owners
- Update `docs/SECURITY_RELEASE_GATES.md` and this playbook if controls changed
