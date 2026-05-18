# Changelog

All notable changes to the **Karma** public repository are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) for release tags when published.

## [Unreleased]

### Added

- Phase 1 Open Wallet signing: EIP-712 trade launch, `sdk/signing_backend.py`, signing-preview APIs, daily launch budget checks (`docs/OPEN_WALLET_SIGNING-zh.md`).
- Public testing acceptance summaries: `docs/public-testing/TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md`, `STRESS_ATTACK_ACCEPTANCE_2026-05-17.md`.
- Integration test for triangle settlement cycle `A→B→C→A` (`tests/integration/test_triangle_settlement_cycle.py`).

### Changed

- Rate limit: in-process sliding window fallback when Redis is unavailable (mitigates register flood; production should use Redis + fail-closed).
- Receipt chronology: reject `started_at` earlier than prior receipt on the same task.

### Security

- Documented 2026-05-17 stress/attack (3,143 tests) and testnet pre-auth (353 tests) results in `docs/public-testing/`.

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
