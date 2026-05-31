# Karma — Documentation Index

## Getting Started

| Document | Description |
|----------|-------------|
| [GETTING_STARTED.md](./GETTING_STARTED.md) | Quickstart guide for new developers |
| [ONBOARDING.md](./ONBOARDING.md) | Developer onboarding checklist |
| [ROADMAP.md](./ROADMAP.md) | Project roadmap and milestones |
| [FOCUS_ROADMAP.md](./FOCUS_ROADMAP.md) | Current sprint focus areas |

## Architecture & Protocol

| Document | Description |
|----------|-------------|
| [PROOF_LAYER.md](./PROOF_LAYER.md) | Karma proof primitives: Receipts, Bundles, Verification |
| [EXECUTION_RECEIPT_STANDARD.md](./EXECUTION_RECEIPT_STANDARD.md) | Execution receipt schema V1 (bill-based) |
| [EXECUTION_RECEIPT_STANDARD_V2.md](./EXECUTION_RECEIPT_STANDARD_V2.md) | Execution receipt schema V2 (binding-based, for KarmaBilateral) |
| [EVIDENCE_BUNDLE_STANDARD.md](./EVIDENCE_BUNDLE_STANDARD.md) | Evidence bundle JSON schema and hashing rules |
| [SETTLEMENT_FLOW_PUBLIC.md](./SETTLEMENT_FLOW_PUBLIC.md) | Public settlement flow documentation |
| [DISPUTE_FLOW_PUBLIC.md](./DISPUTE_FLOW_PUBLIC.md) | Public dispute resolution flow |
| [SIGNING_PAYLOAD_SPEC.md](./SIGNING_PAYLOAD_SPEC.md) | Wallet signature payload specification |
| [TRUST_ENGINE_V1_PUBLIC_SCHEMA.md](./TRUST_ENGINE_V1_PUBLIC_SCHEMA.md) | Trust engine public schema |

## Contracts & Migration

| Document | Description |
|----------|-------------|
| [MIGRATION_NCPA_TO_BILATERAL.md](./MIGRATION_NCPA_TO_BILATERAL.md) | Migration guide: NonCustodialAgentPayment → KarmaBilateral |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Deployment SOP (Docker, PostgreSQL, Redis, MinIO) |
| [TESTNET_DEVELOPER_QUICKSTART.md](./TESTNET_DEVELOPER_QUICKSTART.md) | Testnet developer onboarding |
| [TESTNET_RUNBOOK.md](./TESTNET_RUNBOOK.md) | Testnet operations runbook |
| [migrations/v1-public-testnet-prep.md](./migrations/v1-public-testnet-prep.md) | Phase 2 testnet migration note |

## Testing & Quality

| Document | Description |
|----------|-------------|
| [TEST_REPORT_2026-05-31.md](./TEST_REPORT_2026-05-31.md) | Aggregate test report (172 tests, 11 suites) |
| [testnet-integration-checklist.md](./testnet-integration-checklist.md) | Integration test checklist |
| [testnet-readiness-report-2026-05-23.md](./testnet-readiness-report-2026-05-23.md) | Testnet readiness assessment |
| [STRESS_TEST_RUNBOOK.md](./STRESS_TEST_RUNBOOK.md) | Stress test procedures |
| [public-testing/](./public-testing/) | Public testing acceptance reports |

## Security

| Document | Description |
|----------|-------------|
| [SECURITY_AUDIT_2026.md](./SECURITY_AUDIT_2026.md) | 2026 security audit summary |
| [security-audit-2026-04-30.md](./security-audit-2026-04-30.md) | Detailed security audit (2026-04-30) |
| [security-audit-2026-05-06-final.md](./security-audit-2026-05-06-final.md) | Final security audit (2026-05-06) |
| [SECURITY_DISCLOSURE.md](./SECURITY_DISCLOSURE.md) | Vulnerability disclosure policy |
| [SECURITY_INCIDENT_PLAYBOOK.md](./SECURITY_INCIDENT_PLAYBOOK.md) | Incident response playbook |
| [SECURITY_RELEASE_GATES.md](./SECURITY_RELEASE_GATES.md) | Release security gates |
| [SECURITY_UPGRADE_PLAN.md](./SECURITY_UPGRADE_PLAN.md) | Security upgrade roadmap |
| [AGENT_GUARD_SECURITY_HARDENING.md](./AGENT_GUARD_SECURITY_HARDENING.md) | Agent guard hardening guide |
| [AGENT_SAFETY_GUARDIAN_V01.md](./AGENT_SAFETY_GUARDIAN_V01.md) | Agent safety guardian spec V0.1 |
| [PRODUCT_SECURITY_REQUIREMENTS.md](./PRODUCT_SECURITY_REQUIREMENTS.md) | Product security requirements |
| [security-boundary.md](./security-boundary.md) | Security boundary definition |

## Integration & SDK

| Document | Description |
|----------|-------------|
| [API_REFERENCE.md](./API_REFERENCE.md) | Full API reference |
| [API_AUTH.md](./API_AUTH.md) | API authentication guide |
| [API_ROADMAP_V01.md](./API_ROADMAP_V01.md) | API roadmap V0.1 |
| [INTEGRATIONS.md](./INTEGRATIONS.md) | External integrations (x402, AP2, MCP, OpenClaw) |
| [AGENT_INTEGRATION.md](./AGENT_INTEGRATION.md) | Agent integration guide |
| [sdk-quickstart.md](./sdk-quickstart.md) | SDK quickstart |
| [mcp-adapter-guide.md](./mcp-adapter-guide.md) | MCP adapter guide |
| [integration-guide.md](./integration-guide.md) | General integration guide |
| [agent-runtime-integration.md](./agent-runtime-integration.md) | Agent runtime integration |
| [runtime-key-guide.md](./runtime-key-guide.md) | Runtime key management |

## Operations

| Document | Description |
|----------|-------------|
| [OPENCLAW_P1_DUAL_AGENT.md](./OPENCLAW_P1_DUAL_AGENT.md) | OpenClaw P1 dual agent ops |
| [PRIVATE_REPO_BOOTSTRAP.md](./PRIVATE_REPO_BOOTSTRAP.md) | Private repo bootstrap |
| [PRIVATE_REPO_SPLIT_GUIDE.md](./PRIVATE_REPO_SPLIT_GUIDE.md) | Public/private repo split guide |
| [PUBLIC_PRIVATE_OPERATIONS.md](./PUBLIC_PRIVATE_OPERATIONS.md) | Public-private operations sync |
| [PUBLIC_PRIVATE_SYNC.md](./PUBLIC_PRIVATE_SYNC.md) | Public-private sync procedures |
| [PRODUCTION_PRELAUNCH_CHECKLIST-zh.md](./PRODUCTION_PRELAUNCH_CHECKLIST-zh.md) | Production pre-launch checklist (ZH) |
| [COMMERCIAL_READINESS_CHECKLIST_V01.md](./COMMERCIAL_READINESS_CHECKLIST_V01.md) | Commercial readiness checklist |

## Ecosystem & Strategy

| Document | Description |
|----------|-------------|
| [KARMA_ECOSYSTEM_INTEGRATION_ROADMAP-zh.md](./KARMA_ECOSYSTEM_INTEGRATION_ROADMAP-zh.md) | Ecosystem integration roadmap (ZH) |
| [KARMA_FINAL_V1_ENGINEERING_KICKOFF_CN.md](./KARMA_FINAL_V1_ENGINEERING_KICKOFF_CN.md) | Karma V1 engineering kickoff (CN) |
| [KARMA_BFF_OPENMANUS_INTEGRATION.md](./KARMA_BFF_OPENMANUS_INTEGRATION.md) | BFF/OpenManus integration spec |
| [KARMA2_AGENT_KARMA_FINAL_IMPORT.md](./KARMA2_AGENT_KARMA_FINAL_IMPORT.md) | Karma2 final import strategy |
| [PUBLIC_ALIGNMENT_REPORT.md](./PUBLIC_ALIGNMENT_REPORT.md) | Public-private alignment report |
| [PUBLIC_NARRATIVE_AND_COFUNDER_RECRUITMENT.md](./PUBLIC_NARRATIVE_AND_COFUNDER_RECRUITMENT.md) | Public narrative & cofounder recruitment |
| [PUBLIC_REPO_LANDING-zh.md](./PUBLIC_REPO_LANDING-zh.md) | Public repo landing page (ZH) |
| [early-builders-recruitment-zh.md](./early-builders-recruitment-zh.md) | Early builders recruitment (ZH) |

## License & Attribution

| Document | Description |
|----------|-------------|
| [LICENSING.md](./LICENSING.md) | Licensing summary |
| [OPEN_SOURCE_ATTRIBUTION.md](./OPEN_SOURCE_ATTRIBUTION.md) | Open source attribution |
| [OPEN_SOURCE_NOTICE.md](../OPEN_SOURCE_NOTICE.md) | Open source notice (repo root) |
| [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | Code of conduct (repo root) |
| [CHANGELOG.md](../CHANGELOG.md) | Changelog (repo root) |

---

## Document Conventions

- **Language:** English unless `-zh` or `-cn` suffix (Chinese)
- **Status indicators:** Draft, Review, Final (see document headers)
- **Files with `_` prefix** are internal/public; files without may reference private components
- **`docs/public-testing/`** — Public testnet acceptance and security test reports

## Quick Links by Role

| Role | Key Documents |
|------|---------------|
| **New developer** | GETTING_STARTED → ONBOARDING → sdk-quickstart → TESTNET_DEVELOPER_QUICKSTART |
| **Contract integrator** | MIGRATION_NCPA_TO_BILATERAL → EXECUTION_RECEIPT_STANDARD_V2 → API_REFERENCE |
| **Security reviewer** | SECURITY_AUDIT_2026 → security-audit-2026-05-06-final → SECURITY_INCIDENT_PLAYBOOK |
| **Operator** | DEPLOYMENT → TESTNET_RUNBOOK → PUBLIC_PRIVATE_OPERATIONS |
| **Ecosystem partner** | INTEGRATIONS → KARMA_ECOSYSTEM_INTEGRATION_ROADMAP-zh → early-builders-recruitment-zh |
