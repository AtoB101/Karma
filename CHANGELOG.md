# Changelog

All notable changes to the **Karma** public repository are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) for release tags when published.

## [Unreleased]

### Added

- Public testnet go-live: `PUBLIC_TESTNET_GO_LIVE-zh.md`, `OPTIMIZATION_BACKLOG_POST_AUDIT-zh.md`, `public_testnet_preflight.sh`; CI runs `full_chain_audit_gate.sh`.
- Full-chain audit gate: `full_chain_audit_gate.sh`, `reverse_rule_audit.py`, `testnet_claw_manus_gate.sh`, `FULL_CHAIN_AUDIT_ACCEPTANCE-zh.md`.
- Phase 3 AP2: `trusted_agent_runtime/ap2_adapter.py`, `docs/AP2_EVIDENCE_PROFILE-zh.md`, SD-JWT export (`services/evidence_export.py`).
- Phase 3 Payment Intent: `POST/GET /v1/payment-intents`, bind endpoint, settlement → `settled` sync; migrations `0027`–`0028`.
- Phase 3 Evidence API: `GET /v1/evidence/{id}`, `verify`, `verify-external`; `human_not_present_allowed` on automation policy.
- Phase 2 x402: `sdk/x402/` client/middleware, `POST /v1/x402/pay-and-fetch`, `ExecutionReceipt.external_payment`, settlement `funding_source`, OpenClaw `karma_x402_fetch`, `examples/x402_agent_buy_api/`.
- Phase 2 x402 backends: `env` (EIP-191 signed PAYMENT-SIGNATURE), `sepolia` (ERC-20 USDC transfer on testnet).
- Ecosystem integration phased roadmap: `docs/KARMA_ECOSYSTEM_INTEGRATION_ROADMAP-zh.md` (Open Wallet, x402, AP2, governance, commercial).
- Public testing acceptance summaries: `docs/public-testing/TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md`, `STRESS_ATTACK_ACCEPTANCE_2026-05-17.md`.
- Integration test for triangle settlement cycle `A→B→C→A` (`tests/integration/test_triangle_settlement_cycle.py`).

### Changed

- Sentinel audit: fix two non-blocking test failures (receipt relax pin + UTC deadline); add `test_sentinel_nonblocking_regressions.py` and `tests/helpers/time_test_utils.py`.
- Tests (PR #94): receipt missing-signature pins strict policy; voucher attestation uses UTC-aware deadline.
- Production gates: `X402_PAYMENT_BACKEND=sepolia` in `phase1_open_wallet_gate.sh` and `production-prelaunch-gate.sh` (Phase 2 prod validator).
- Idempotency error message generalized for PaymentIntent (`trade_pipeline_security.py`).
- Rate limit: in-process sliding window fallback when Redis is unavailable (mitigates register flood; production should use Redis + fail-closed).
- Receipt chronology: reject `started_at` earlier than prior receipt on the same task.

### Security

- Documented 2026-05-17 stress/attack (3,143 tests) and testnet pre-auth (353 tests) results in `docs/public-testing/`.

## [2026-05-18] — Phase 1 Open Wallet + OpenClaw local (on `main` @ `81d20b0`)

### Added

- OpenClaw local delivery signature relax (`OPENCLAW_LOCAL_PHASE1_AUTO_RELAX`); `deploy/.env.local-openclaw.example`.
- EIP-712 path B local template: `deploy/.env.local-eip712.example`; `scripts/acceptance/phase1_eip712_launch_smoke.py`.
- OpenManus `KarmaRuntimeClient.trade_launch_sign_with_backend()`.

### Fixed

- OpenClaw path A9: seller `karma_submit_execution_receipt` / `karma_submit_progress` in local Phase 1 (`services/receipt_guard.py`, PR #88).

## [2026-05-18] — Phase 1 Open Wallet signing (on `main` @ `84b9345`)

### Added

- Phase 1 Open Wallet signing: EIP-712 `TradeLaunchIntent`, `sdk/signing_backend.py`, signing-preview / sign-with-backend APIs, daily launch budget checks (`docs/OPEN_WALLET_SIGNING-zh.md`).
- Phase 1.5 unification: `trade_launch_attestation` in voucher spec, `voucher_buyer_commitment` dual-path verify, runtime daily spend mirror, production gates for trade EIP-712.
- Phase 1 acceptance: `docs/public-testing/PHASE1_OPEN_WALLET_ACCEPTANCE.md`, `scripts/acceptance/phase1_open_wallet_gate.sh`.
- OpenClaw MCP: `karma_trade_launch_signing_preview`, `karma_trade_launch_sign_with_backend`; OpenManus `trade_launch_signing_preview()`.

### Security

- Attack matrix KSA-TL-001..005 in `docs/public-testing/attack-testing-roadmap.md`; covered by `tests/unit/test_trade_launch_security.py`.

## [2026-05-17] — Phase 1 trade, SDK, production gates (on `main` @ `ee68f62`)

### Added

- Phase 1 payment codes, preauth auto accept/reject, full trade launch pipeline, Console trade hub.
- OpenClaw phase1 MCP tools; OpenManus `KarmaRuntimeClient`.
- `docs/PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md`, `docs/TESTNET_PHASE1_TRADE_ACCEPTANCE-zh.md`, `docs/PRODUCTION_PRELAUNCH_CHECKLIST-zh.md` (see merged PRs #78–#82).

### Added (earlier unreleased docs)

- Public landing guide (`docs/PUBLIC_REPO_LANDING-zh.md`) and private-repo execution checklist (`docs/PRIVATE_REPO_EXECUTION_CHECKLIST-zh.md`).
- OpenClaw operator one-page checklist (`docs/OPENCLAW_OPERATOR_CHECKLIST-zh.md`).
- GitHub issue/PR templates and `CODE_OF_CONDUCT.md`.

### Changed

- README quickstart uses canonical clone URL `https://github.com/AtoB101/Karma.git`; license section aligned with AGPL-3.0-only.

## [2026-05-16] — OpenClaw authorization chain (on `main`)

### Added

- Server-side automation policy (`agent_automation_policies`), readiness API, handoff attestation.
- Runtime gates: saved policy, task automation readiness, wallet binding, daily spend persistence.
- Console Settings six-step authorization flow; MCP `karma_check_automation_readiness`.
- Production validator for `APP_ENV=production` Runtime flags.

See `docs/OPENCLAW_P1_DUAL_AGENT.md` and `deploy/one-click-deploy.md` for operations.
