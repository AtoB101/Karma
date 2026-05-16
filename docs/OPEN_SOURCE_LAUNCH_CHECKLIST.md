# Karma Open Source Launch Checklist

This checklist is a practical launch plan for opening Karma to external builders
while preserving focus on the core settlement story:

> EIP-712 signed off-chain intent -> on-chain verifiable settlement

## 1) Repository Readiness (must have)

- [x] License file present (`LICENSE`, AGPL-3.0-only)
- [x] `README.md` states problem, core flow, and quickstart clearly (canonical clone: `AtoB101/Karma`)
- [x] `SECURITY.md` available with disclosure process and proof boundaries
- [x] `docs/SECURITY_SUMMARY_CN_EN.md` linked for external stakeholders
- [x] `docs/SIGNING_PAYLOAD_SPEC.md` covers backend integration details
- [x] `foundry.lock` and `lib/forge-std` pinned for reproducibility

## 2) Contribution Infrastructure (must have)

- [x] `CONTRIBUTING.md` with local setup, coding style, and PR flow
- [x] `CODE_OF_CONDUCT.md` for community behavior standards
- [x] Issue templates:
  - [x] bug report
  - [x] feature request
  - [x] security concern redirect (non-public)
- [x] Pull request template with:
  - [x] scope
  - [x] test evidence
  - [x] risk notes

## 3) Quality Gates (must have)

- [x] CI required on all PRs:
  - [x] `forge test -vv` (`.github/workflows/forge-ci.yml`)
  - [x] core scenario test (`ScenarioFlow` — via forge-ci / python acceptance)
  - [x] at least one invariant suite (`security-ci.yml`)
- [x] Scheduled security jobs:
  - [x] Slither
  - [x] Echidna
- [ ] Release/security milestone jobs:
  - [ ] Certora critical rule set (optional milestone)

## 4) Release Shape (should have)

- [x] `CHANGELOG.md` initialized
- [ ] Semantic versioning policy documented (see `CHANGELOG.md` header; tag policy TBD)
- [ ] Tags for stable demo baselines (for reproducible references)
- [x] Minimal architecture diagram (README Architecture section)

## 5) Community Narrative (should have)

- [x] One sentence positioning for all channels (README lede)
- [x] "Do one thing well" scope statement pinned in README
- [x] Public roadmap split by:
  - [x] V1 core settlement (`docs/PUBLIC_NARRATIVE_AND_COFUNDER_RECRUITMENT.md`, kickoff doc)
  - [ ] V1.5 integration polish (tracked in issues)
  - [ ] V2 optional expansion

## 6) Suggested Launch Sequence

1. Freeze a release candidate commit.
2. Run full quality gates and archive evidence artifacts.
3. Publish release notes with known limits and deferred scope.
4. Announce with:
   - one-page security summary,
   - demo command (`./scripts/run_focus_demo.sh`),
   - contribution guide.
5. Triage first external issues and tighten docs from real feedback.

## 7) Exit Criteria (ready to go public)

- [x] New contributor can run demo in one command (`examples/demo_captioning.py`)
- [x] New contributor can run full tests from docs only (`CONTRIBUTING.md` / README)
- [x] Security posture can be understood from README + SECURITY docs
- [x] Core flow is explained in under one minute without module overload

## Related landing docs

- Public: `docs/PUBLIC_REPO_LANDING-zh.md`
- Private (Karma2): `docs/PRIVATE_REPO_EXECUTION_CHECKLIST-zh.md`
- Cross-repo ops: `docs/PUBLIC_PRIVATE_OPERATIONS.md`
