# Security Release Gates (Public Test Launch)

This checklist is blocking for broad public test rollout.

## Gate A — Identity and Access
- [ ] `APP_ENV=production`
- [ ] `APP_SECRET_KEY` is rotated and non-default
- [ ] `AUTH_ENFORCE_PROTECTED_ROUTES=true`
- [ ] `AUTH_API_KEYS` configured for all service agents
- [ ] No test credentials are present in runtime env

## Gate B — API Abuse Resistance
- [ ] Redis-backed rate limiter is reachable in production
- [ ] Sensitive write paths have active limits (`write_sensitive` / `state_transition`)
- [ ] Alerting exists for sustained 429 spikes and auth failures
- [ ] `/v1/security/ops/alerts` is monitored with tuned thresholds
- [ ] Alert cooldown / suppression policy is configured and reviewed with on-call
- [ ] Endpoint / route-group threshold overrides are configured for critical paths
- [ ] Active security threshold policy version is pinned and documented

## Gate C — Security Auditability
- [ ] Security audit logs are collected for sensitive write methods
- [ ] Logs include actor ID (when available), request path, method, status, request ID
- [ ] Log retention and query access are configured for incident response

## Gate D — Error Surface Control
- [ ] Internal exceptions are not returned to public clients
- [ ] Private runtime errors are masked behind generic boundary messages
- [ ] Debug mode is disabled in production

## Gate E — Verification and Rollback
- [ ] Security regression tests pass in CI
- [ ] Public acceptance script passes
- [ ] `scripts/public-beta-security-gate.sh` passes in release environment
- [ ] Rollback plan and on-call runbook are confirmed (`docs/SECURITY_INCIDENT_PLAYBOOK.md`)
- [ ] `SECURITY_ONCALL_PRIMARY` / `SECURITY_ONCALL_BACKUP` are configured
- [ ] Baseline drift strategy (`baseline_window_minutes` / `baseline_drift_multiplier`) is reviewed
- [ ] Policy-center rollback drill (`/v1/security/policies/rollback`) has been exercised

