# P0 Secrets and Key Management Baseline V1 (Private)

Status: Security baseline  
Scope: `trust-chain-engine` only (do not publish)

Related docs:

- `docs/P0_RELEASE_GATING_AND_CHANGE_FREEZE_V1.md`
- `docs/P0_RACI_AND_DECISION_AUTHORITY_V1.md`
- `docs/P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`

## 1. Purpose

Define minimum enforceable controls for secrets and key management in P0:

1. prevent fund-loss incidents from key leakage
2. reduce blast radius of credential compromise
3. enforce auditable access and rotation discipline

This baseline is mandatory before production-like traffic expansion.

## 2. Asset classification

Classify all sensitive assets into four classes:

### Class A (critical funds and signing authority)

- settlement signer private keys
- treasury and payout wallet private keys
- HSM/KMS master keys

### Class B (security control and privileged infra)

- database admin credentials
- cloud root/organization credentials
- CI/CD deployment tokens with write privilege

### Class C (service operation secrets)

- provider API secrets
- internal service-to-service tokens
- webhook signing secrets

### Class D (lower-risk but still confidential)

- analytics read-only tokens
- non-privileged environment variables with internal metadata

## 3. Storage policy

Hard requirements:

1. No secrets in source code, markdown, or git history.
2. No plaintext secrets in local `.env` files on shared machines.
3. All Class A/B secrets must live in managed secret store (KMS/HSM/Vault equivalent).
4. Secrets access must be identity-based, not shared static credentials.

Recommended structure:

- secret path naming:
  - `p0/<env>/<service>/<secret-name>`
- version labels:
  - `active`, `next`, `rollback`

## 4. Access control (least privilege)

Rules:

1. Default deny on all secrets.
2. Grant read by runtime role only.
3. Human read access for Class A secrets is prohibited.
4. Break-glass access must be time-limited and ticket-linked.

Minimum approval model:

- Class A/B access policy change requires 2 approvals:
  - security owner
  - platform owner

## 5. Key lifecycle management

## 5.1 Generation

- Class A keys must be generated inside HSM/KMS when feasible.
- If software key generation is required, host must be isolated and ephemeral.

## 5.2 Rotation cadence

- Class A: rotate every 30 days (or faster after any incident)
- Class B: rotate every 60 days
- Class C: rotate every 30-45 days
- Class D: rotate every 90 days

## 5.3 Emergency rotation

Immediate rotation required when:

1. credential appears in logs/chat/tickets
2. unauthorized access suspected
3. compromise indicator from provider/cloud

Mandatory steps:

1. revoke old credential
2. issue new credential
3. validate service health
4. record incident and remediation

## 6. Environment variable policy

Allowed:

- secret references (e.g., vault path IDs)
- non-sensitive configuration

Disallowed:

- raw private keys
- raw API keys
- plaintext database admin passwords

Runtime loading:

1. load secrets at process start from secret manager
2. avoid writing secrets to disk
3. avoid printing secret values in logs

## 7. CI/CD security baseline

CI/CD requirements:

1. secrets only via secure CI secret store
2. no secrets in workflow YAML plaintext
3. protected branches require passing secret-scan checks
4. deployment to protected env requires approval gate

Runner requirements:

- ephemeral runners preferred
- workspace cleanup after run
- command logging redaction enabled

## 8. Logging and observability controls

Must enforce:

1. automatic secret redaction patterns in logs
2. blocklist for known key formats (private key, API key patterns)
3. alert on suspected secret output in logs

Never log:

- full private keys
- full auth tokens
- full webhook secrets

Use masked forms:

- show first 4 + last 4 chars only

## 9. Backup and recovery

For Class A keys:

1. encrypted backup with split custody
2. restore drill at least once per quarter
3. documented key-loss recovery procedure

Recovery drill evidence must include:

- drill date
- participants
- restore success/failure
- follow-up actions

## 10. Compliance and audit requirements

Weekly checks:

- [ ] secret scan report reviewed
- [ ] high-privilege access changes reviewed
- [ ] emergency access events reviewed

Monthly checks:

- [ ] rotation SLA compliance report
- [ ] dormant credential cleanup
- [ ] policy exception review

## 11. Incident handling for key exposure

If key exposure is suspected:

1. classify severity (Sev-1 if Class A, Sev-2 if Class B)
2. revoke and rotate immediately
3. freeze impacted release/deployment flows
4. run integrity checks on settlements and payouts
5. publish internal postmortem within 48h

## 12. Minimum conformance checklist

Before P0 expansion:

- [ ] all Class A secrets migrated to managed store
- [ ] no plaintext keys in repo and docs
- [ ] automated secret scan in CI is blocking
- [ ] break-glass workflow tested
- [ ] rotation calendar and owners assigned
- [ ] key exposure drill completed

## 13. Owner map

- Security owner:
- Platform owner:
- Settlement signer owner:
- CI/CD owner:
- Audit owner:

## 14. Baseline review cadence

- Review this document every 30 days during P0
- Update immediately after any security incident

