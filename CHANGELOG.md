# Changelog

All notable changes to the **Karma** public repository are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) for release tags when published.

## [Unreleased]

### Added

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
