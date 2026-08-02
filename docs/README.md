# Karma Docs Index

Active protocol: **KarmaBilateral** (`lock → bind → settle → finalizeSettle`) + off-chain P1–P8 plates.  
Start at the root [README.md](../README.md) for the repo map.

## Start here

| Doc | Purpose |
|-----|---------|
| [GETTING_STARTED.md](./GETTING_STARTED.md) | Local setup |
| [QUICKSTART_15MIN.md](./QUICKSTART_15MIN.md) | Short path to first calls |
| [ONBOARDING.md](./ONBOARDING.md) | Developer checklist |
| [integration-guide.md](./integration-guide.md) | Public integration surface |
| [AGENT_INTEGRATION.md](./AGENT_INTEGRATION.md) | Agent / runtime integration |
| [AGENT_ONE_CLICK_CONNECT_V1.md](./AGENT_ONE_CLICK_CONNECT_V1.md) | One-click vertical connect |
| [PILOT_E2E_PATH.md](./PILOT_E2E_PATH.md) | **Canonical Sepolia Bilateral E2E** (lock→finalize) |

## Protocol plates (P1–P8)

| Plate | Doc |
|-------|-----|
| P1 Onboarding | [AGENT_P1_ONBOARDING_V1.md](./AGENT_P1_ONBOARDING_V1.md) |
| P2 Boundary | [AGENT_BOUNDARY_STANDARD_V1.md](./AGENT_BOUNDARY_STANDARD_V1.md), [AGENT_BOUNDARY_P2_ENFORCEMENT_V1.md](./AGENT_BOUNDARY_P2_ENFORCEMENT_V1.md) |
| P3 Discovery | [DISCOVERY_PRIORITY_V1.md](./DISCOVERY_PRIORITY_V1.md) |
| P4 Human confirm | [HUMAN_CONFIRMATION_P4_V1.md](./HUMAN_CONFIRMATION_P4_V1.md), [HUMAN_CONFIRMATION_POLICY_V1.md](./HUMAN_CONFIRMATION_POLICY_V1.md) |
| P5 Important fields | [IMPORTANT_FIELDS_P5_V1.md](./IMPORTANT_FIELDS_P5_V1.md), [IMPORTANT_FIELDS_STANDARD_V1.md](./IMPORTANT_FIELDS_STANDARD_V1.md) |
| P6 Accept / TTL | [ACCEPT_FULFILLMENT_P6_V1.md](./ACCEPT_FULFILLMENT_P6_V1.md) |
| P7 Delivery verify | [DELIVERY_VERIFICATION_P7_V1.md](./DELIVERY_VERIFICATION_P7_V1.md) |
| P8 Settlement reputation | [SETTLEMENT_REPUTATION_P8_V1.md](./SETTLEMENT_REPUTATION_P8_V1.md) |

## Settlement & evidence

| Doc | Purpose |
|-----|---------|
| [SETTLEMENT_FLOW_PUBLIC.md](./SETTLEMENT_FLOW_PUBLIC.md) | Bilateral settle flow |
| [DISPUTE_FLOW_PUBLIC.md](./DISPUTE_FLOW_PUBLIC.md) | Dispute surface |
| [EXECUTION_RECEIPT_STANDARD_V2.md](./EXECUTION_RECEIPT_STANDARD_V2.md) | Receipts (binding-based) |
| [EXECUTION_RECEIPT_STANDARD.md](./EXECUTION_RECEIPT_STANDARD.md) | Receipts V1 (legacy schema note) |
| [EVIDENCE_BUNDLE_STANDARD.md](./EVIDENCE_BUNDLE_STANDARD.md) | Evidence bundles |
| [TRUST_ENGINE_V1_PUBLIC_SCHEMA.md](./TRUST_ENGINE_V1_PUBLIC_SCHEMA.md) | Public-safe evidence field markers (CI gate) |
| [TESTNET_RUNBOOK.md](./TESTNET_RUNBOOK.md) | Testnet Bilateral ops |
| [TESTNET_DEVELOPER_QUICKSTART.md](./TESTNET_DEVELOPER_QUICKSTART.md) | Testnet onboarding |

## API & SDK

| Doc | Purpose |
|-----|---------|
| [API_REFERENCE.md](./API_REFERENCE.md) | HTTP API |
| [API_AUTH.md](./API_AUTH.md) | Auth |
| [sdk-quickstart.md](./sdk-quickstart.md) | SDK |
| [runtime-key-guide.md](./runtime-key-guide.md) | Runtime keys |
| [INTEGRATIONS.md](./INTEGRATIONS.md) | x402 / AP2 / MCP / OpenClaw overview |
| [X402_INTEGRATION-zh.md](./X402_INTEGRATION-zh.md) | x402 |
| [AP2_EVIDENCE_PROFILE-zh.md](./AP2_EVIDENCE_PROFILE-zh.md) | AP2 |
| [KARMA_BFF_OPENMANUS_INTEGRATION.md](./KARMA_BFF_OPENMANUS_INTEGRATION.md) | OpenManus BFF |
| [OPENCLAW_P1_DUAL_AGENT.md](./OPENCLAW_P1_DUAL_AGENT.md) | OpenClaw |
| [mcp-adapter-guide.md](./mcp-adapter-guide.md) | MCP |

## Security & acceptance

| Doc | Purpose |
|-----|---------|
| [SECURITY_DISCLOSURE.md](./SECURITY_DISCLOSURE.md) | Vulnerability disclosure |
| [SECURITY_INCIDENT_PLAYBOOK.md](./SECURITY_INCIDENT_PLAYBOOK.md) | Incident response |
| [SECURITY_RELEASE_GATES.md](./SECURITY_RELEASE_GATES.md) | Release gates |
| [security-boundary.md](./security-boundary.md) | Public/private boundary |
| [STRESS_TEST_RUNBOOK.md](./STRESS_TEST_RUNBOOK.md) | Stress procedures |
| [ADVERSARIAL_FULLCHAIN_AUDIT_V1.md](./ADVERSARIAL_FULLCHAIN_AUDIT_V1.md) | Full-chain adversarial |
| [ADVERSARIAL_WHOLE_PROJECT_AUDIT_V1.md](./ADVERSARIAL_WHOLE_PROJECT_AUDIT_V1.md) | Whole-project adversarial |
| [public-testing/](./public-testing/) | Phase acceptance packs |

## Ops / deploy

| Doc | Purpose |
|-----|---------|
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Deploy |
| [FOCUS_ROADMAP.md](./FOCUS_ROADMAP.md) | Near-term focus |
| [wallet-signature-payload-examples.json](./wallet-signature-payload-examples.json) | Wallet payload examples |
| [testnet-integration-checklist.md](./testnet-integration-checklist.md) | Integration checklist |
| [migrations/v1-public-testnet-prep.md](./migrations/v1-public-testnet-prep.md) | Payload migration note |

## Product narrative

| Doc | Purpose |
|-----|---------|
| [whitepaper.md](./whitepaper.md) | Protocol narrative |

**Removed:** dated NCPA/Guard audits, private-repo process dumps, marketing shells, and duplicate lowercase standards. Use this index + root README only.
